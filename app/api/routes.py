from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.access_control import AccessControlResult, detect_access_control, skipped_creator_from_access
from app.models.schemas import (
    AnalyzeProfileRequest,
    AnalyzeProfileResponse,
    CreatorAnalysis,
    MatchBriefRequest,
    MatchBriefResponse,
)
from app.services.analyzer import analyze_with_llm, get_analyzer_metadata
from app.services.matcher import match_brief
from app.services.scraper import (
    MANUAL_VERIFICATION_UNAVAILABLE_MESSAGE,
    ManualBrowserSession,
    ManualVerificationUnavailable,
    close_manual_session,
    detect_platform,
    scrape_from_manual_session,
    scrape_profile,
    start_manual_session,
)
from app.storage.database import get_connection, init_db, save_creator_analysis


router = APIRouter()


@dataclass
class PausedTask:
    task_id: str
    profile_url: str
    brand_brief: str | None
    platform: str
    status: str
    created_at: float
    updated_at: float
    session: ManualBrowserSession
    save_to_db: bool
    debug: bool


PAUSED_TASKS: dict[str, PausedTask] = {}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/analyze-profile",
    response_model=AnalyzeProfileResponse | CreatorAnalysis,
    response_model_exclude_none=True,
)
async def analyze_profile(request: AnalyzeProfileRequest) -> AnalyzeProfileResponse | CreatorAnalysis | JSONResponse:
    platform_name = detect_platform(str(request.profile_url))
    try:
        if request.manual_verification:
            task_id = make_task_id()
            scrape, session = await start_manual_session(str(request.profile_url), task_id)
        else:
            task_id = make_resume_token(str(request.profile_url))
            session = None
            scrape = await scrape_profile(
                str(request.profile_url),
                manual_verification=False,
            )
    except ManualVerificationUnavailable as exc:
        return manual_verification_unavailable_response(platform_name, str(exc))
    except Exception as exc:
        if request.manual_verification:
            return manual_verification_unavailable_response(platform_name)
        return AnalyzeProfileResponse(
            status="failed",
            manual_verification_required=False,
            platform=platform_name,
            message=str(exc),
        )

    access = detect_access_control(scrape)
    if access.should_skip_llm:
        if request.manual_verification and session is not None:
            PAUSED_TASKS[task_id] = PausedTask(
                task_id=task_id,
                profile_url=str(request.profile_url),
                brand_brief=request.brand_brief,
                platform=access.platform,
                status=access.access_status,
                created_at=time.time(),
                updated_at=time.time(),
                session=session,
                save_to_db=request.save_to_db,
                debug=request.debug,
            )
        return access_control_response(
            scrape=scrape,
            access=access,
            task_id=task_id,
            debug=request.debug,
            has_live_session=request.manual_verification and session is not None,
        )

    creator = await analyze_with_llm(scrape, request.brand_brief)
    if request.manual_verification and session is not None:
        await close_manual_session(session)

    if request.save_to_db:
        with get_connection() as conn:
            init_db(conn)
            save_creator_analysis(conn, creator)

    if request.debug:
        metadata = get_analyzer_metadata()
        return AnalyzeProfileResponse(
            status="completed",
            manual_verification_required=False,
            platform=scrape.platform,
            creator=creator,
            raw_extraction=scrape.to_dict(),
            access_control=access.to_dict(),
            **metadata,
        )

    return creator


@router.post(
    "/resume-task/{task_id}",
    response_model=AnalyzeProfileResponse | CreatorAnalysis,
    response_model_exclude_none=True,
)
async def resume_task(task_id: str) -> AnalyzeProfileResponse | CreatorAnalysis:
    task = PAUSED_TASKS.get(task_id)
    if task is None:
        return AnalyzeProfileResponse(
            status="failed",
            manual_verification_required=False,
            message="Paused task not found or already completed.",
            resume_token=task_id,
        )

    scrape = await scrape_from_manual_session(task.session, task.profile_url)
    access = detect_access_control(scrape)
    task.updated_at = time.time()
    task.status = access.access_status

    if access.should_skip_llm:
        return access_control_response(
            scrape=scrape,
            access=access,
            task_id=task_id,
            debug=task.debug,
            has_live_session=True,
        )

    creator = await analyze_with_llm(scrape, task.brand_brief)
    if task.save_to_db:
        with get_connection() as conn:
            init_db(conn)
            save_creator_analysis(conn, creator)
    await close_manual_session(task.session)
    PAUSED_TASKS.pop(task_id, None)

    if task.debug:
        metadata = get_analyzer_metadata()
        return AnalyzeProfileResponse(
            status="completed",
            manual_verification_required=False,
            platform=scrape.platform,
            creator=creator,
            raw_extraction=scrape.to_dict(),
            access_control=access.to_dict(),
            **metadata,
        )
    return creator


@router.post("/match-brief", response_model=MatchBriefResponse)
def match_profile_brief(request: MatchBriefRequest) -> MatchBriefResponse:
    with get_connection() as conn:
        init_db(conn)
        candidates = match_brief(conn, request.brand_brief, request.limit)
    return MatchBriefResponse(candidates=candidates)


def make_resume_token(profile_url: str) -> str:
    return hashlib.sha1(profile_url.encode("utf-8")).hexdigest()[:16]


def make_task_id() -> str:
    return f"task_{uuid4().hex[:12]}"


def access_control_response(
    scrape,
    access: AccessControlResult,
    task_id: str,
    debug: bool,
    has_live_session: bool,
) -> AnalyzeProfileResponse:
    message = (
        "Login or verification is required. Please complete it in the opened browser, "
        f"then call /resume-task/{task_id}."
        if has_live_session
        else "Login, verification, or a valid creator page is required. Retry with "
        "manual_verification=true to open a browser and pause the task."
    )
    creator = CreatorAnalysis.model_validate(skipped_creator_from_access(scrape, access)) if debug else None
    metadata = get_analyzer_metadata() if debug else {}
    return AnalyzeProfileResponse(
        status=access.access_status if access.access_status != "normal_accessible" else "manual_verification_required",
        manual_verification_required=True,
        platform=access.platform,
        creator=creator,
        raw_extraction=scrape.to_dict() if debug else None,
        access_control=access.to_dict() if debug else None,
        message=message,
        resume_token=task_id,
        analysis_source="skipped_due_to_access_control" if debug else None,
        llm_provider=metadata.get("llm_provider"),
        llm_model=metadata.get("llm_model"),
        api_key_detected=metadata.get("api_key_detected"),
    )


def manual_verification_unavailable_response(
    platform_name: str,
    message: str = MANUAL_VERIFICATION_UNAVAILABLE_MESSAGE,
) -> JSONResponse:
    return JSONResponse(
        {
            "status": "manual_verification_unavailable",
            "manual_verification_required": True,
            "platform": platform_name,
            "message": message,
            "resume_token": None,
        }
    )
