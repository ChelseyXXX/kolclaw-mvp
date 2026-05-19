from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class AnalyzeProfileRequest(BaseModel):
    profile_url: HttpUrl
    brand_brief: str | None = None
    debug: bool = Field(
        default=False,
        description="Return wrapped response with raw_extraction for debugging.",
    )
    manual_verification: bool = Field(
        default=False,
        description="Launch a headed browser and pause if login/CAPTCHA is detected.",
    )
    save_to_db: bool = True


class CreatorAnalysis(BaseModel):
    platform: str = ""
    profile_url: str = ""
    nickname: str = ""
    bio: str = ""
    follower_count: str = "unknown"
    content_categories: list[str] = Field(default_factory=list)
    recent_post_titles: list[str] = Field(default_factory=list)
    recent_post_links: list[str] = Field(default_factory=list)
    brand_fit_tags: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    summary: str = ""


class AnalyzeProfileResponse(BaseModel):
    status: Literal["completed", "manual_verification_required", "failed"]
    manual_verification_required: bool
    creator: CreatorAnalysis | None = None
    raw_extraction: dict[str, Any] | None = None
    message: str | None = None
    resume_token: str | None = None
    analysis_source: Literal["llm", "mock", "rule_based"] | None = None
    llm_provider: Literal["openai", "deepseek", "none"] | None = None
    llm_model: str | None = None
    api_key_detected: bool | None = None


class MatchBriefRequest(BaseModel):
    brand_brief: str
    limit: int = Field(default=5, ge=1, le=20)


class MatchCandidate(BaseModel):
    creator_id: int
    nickname: str
    platform: str
    profile_url: str
    score: float
    matched_signals: list[str]
    risk_flags: list[str]
    summary: str


class MatchBriefResponse(BaseModel):
    candidates: list[MatchCandidate]
