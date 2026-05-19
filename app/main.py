from __future__ import annotations

import hashlib

from fastapi import FastAPI

from app.db import get_connection, init_db, save_creator_analysis
from app.llm import analyze_with_llm, get_analyzer_metadata
from app.matcher import match_brief
from app.schemas import (
    AnalyzeProfileRequest,
    AnalyzeProfileResponse,
    CreatorAnalysis,
    MatchBriefRequest,
    MatchBriefResponse,
)
from app.scraper import scrape_profile


app = FastAPI(title="KOLClaw Creator Analysis MVP", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    with get_connection() as conn:
        init_db(conn)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-profile", response_model=AnalyzeProfileResponse | CreatorAnalysis)
async def analyze_profile(request: AnalyzeProfileRequest) -> AnalyzeProfileResponse | CreatorAnalysis:
    try:
        scrape = await scrape_profile(
            str(request.profile_url),
            manual_verification=request.manual_verification,
        )
    except Exception as exc:
        return AnalyzeProfileResponse(
            status="failed",
            manual_verification_required=False,
            message=str(exc),
        )

    if scrape.manual_verification_required and not request.manual_verification:
        metadata = get_analyzer_metadata() if request.debug else {}
        return AnalyzeProfileResponse(
            status="manual_verification_required",
            manual_verification_required=True,
            raw_extraction=scrape.to_dict() if request.debug else None,
            message=(
                "Login or CAPTCHA-like content was detected. Retry with "
                "`manual_verification=true` to pause in a headed browser."
            ),
            resume_token=make_resume_token(str(request.profile_url)),
            **metadata,
        )

    creator = await analyze_with_llm(scrape, request.brand_brief)

    if request.save_to_db:
        with get_connection() as conn:
            init_db(conn)
            save_creator_analysis(conn, creator)

    if request.debug:
        metadata = get_analyzer_metadata()
        return AnalyzeProfileResponse(
            status="completed",
            manual_verification_required=False,
            creator=creator,
            raw_extraction=scrape.to_dict(),
            **metadata,
        )

    return creator


@app.post("/match-brief", response_model=MatchBriefResponse)
def match_profile_brief(request: MatchBriefRequest) -> MatchBriefResponse:
    with get_connection() as conn:
        init_db(conn)
        candidates = match_brief(conn, request.brand_brief, request.limit)
    return MatchBriefResponse(candidates=candidates)


def make_resume_token(profile_url: str) -> str:
    return hashlib.sha1(profile_url.encode("utf-8")).hexdigest()[:16]
