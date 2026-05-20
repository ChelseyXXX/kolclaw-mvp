from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_env_flag, get_llm_api_key, get_llm_base_url, get_llm_model
from app.models.schemas import CreatorAnalysis
from app.services.scraper import ScrapeResult


SYSTEM_PROMPT = """You are an analyst for KOLClaw.
Analyze a creator homepage for brand brief matching.
Return ONLY valid JSON. Use exactly the required English keys.
All descriptive values must be written in Chinese.
If a field is unknown, use "" for strings, [] for arrays, or "unknown" for follower_count.
Do not invent facts. Infer cautiously and mark uncertainty in risk_flags when needed.
Generate creator-specific categories, brand_fit_tags, risk_flags, and summary from the bio and recent_post_titles.
Do not use generic MVP/template language such as "基于公开页面元数据" or "最小化达人画像分析".
Do not output internal process tags such as "内容可结构化分析", "可进入 brief matching 初筛", or "公开信息抓取风险较低".
Only put real brand-safety, data-quality, authenticity, legal, or content risks in risk_flags.
Do not treat follower size as a risk by itself."""


USER_PROMPT_TEMPLATE = """Brand brief:
{brand_brief}

Raw extracted profile data:
{raw_data}

Required JSON keys:
platform, profile_url, nickname, bio, follower_count, content_categories,
recent_post_titles, recent_post_links, brand_fit_tags, risk_flags, summary

Important:
- Keep factual fields from raw data unless clearly empty: platform, profile_url, nickname, bio, follower_count, recent_post_titles, recent_post_links.
- Generate content_categories from creator bio and post titles.
- Generate brand_fit_tags as practical brand matching signals, not internal process labels.
- Generate a creator-specific summary in Chinese.
"""


ZH_LOW_RISK = "\u516c\u5f00\u4fe1\u606f\u6293\u53d6\u98ce\u9669\u8f83\u4f4e"
ZH_PUBLIC_BIO_MISSING = "\u516c\u5f00\u9875\u9762\u672a\u63d0\u4f9b\u660e\u786e bio"
ZH_LIFESTYLE = "\u65e5\u5e38\u751f\u6d3b"
ZH_FASHION = "\u65f6\u5c1a\u7a7f\u642d"
ZH_FOOD = "\u7f8e\u98df"
ZH_TRAVEL = "\u65c5\u884c"
ZH_FITNESS = "\u8fd0\u52a8\u5065\u5eb7"
ZH_DANCE = "\u821e\u8e48"
ZH_CHOREO = "\u7f16\u821e/\u7ffb\u8df3"
ZH_DANCE_TAG = "\u821e\u8e48\u5185\u5bb9"
ZH_YOUNG_FEMALE_TAG = "\u5e74\u8f7b\u5973\u6027\u53d7\u4f17"
ZH_OUTFIT_TAG = "\u7a7f\u642d\u76f8\u5173"
ZH_SHORT_VIDEO_TAG = "\u9002\u5408\u77ed\u89c6\u9891\u79cd\u8349"
ZH_EDUCATION = "\u6559\u80b2"
ZH_COLLEGE_CONTENT = "\u5927\u5b66\u751f\u5185\u5bb9"
ZH_CAMPUS_CONTENT = "\u6821\u56ed\u5185\u5bb9"
ZH_WORKPLACE_CAMPUS = "\u804c\u573a/\u6821\u56ed\u89c2\u5bdf"
ZH_SHORT_SKIT = "\u77ed\u5267\u60c5/\u6bb5\u5b50"
ZH_ENTERTAINMENT = "\u6cdb\u5a31\u4e50"
ZH_COLLEGE_AUDIENCE_TAG = "\u5927\u5b66\u751f\u53d7\u4f17"
ZH_CAMPUS_TAG = "\u6821\u56ed\u5185\u5bb9"
ZH_EDUCATION_TAG = "\u6559\u80b2\u7c7b\u5185\u5bb9"
ZH_WORKPLACE_TOPIC_TAG = "\u804c\u573a\u8bdd\u9898"
ZH_SHORT_SKIT_TAG = "\u60c5\u666f\u77ed\u5267"
ZH_YOUNG_EMOTION_TAG = "\u5e74\u8f7b\u4eba\u60c5\u7eea\u5171\u9e23"
ZH_CAMPUS_MARKETING_TAG = "\u9002\u5408\u6821\u56ed\u8425\u9500"
ZH_EDU_PRODUCT_TAG = "\u9002\u5408\u77e5\u8bc6/\u6559\u80b2\u4ea7\u54c1\u63a8\u5e7f"
ZH_CREATOR_TOOL_TAG = "\u9002\u5408\u5185\u5bb9\u521b\u4f5c\u5de5\u5177\u63a8\u5e7f"
ZH_MANUAL_RISK = "\u9875\u9762\u53ef\u80fd\u9700\u8981\u767b\u5f55\u6216\u4eba\u673a\u9a8c\u8bc1\uff0c\u81ea\u52a8\u6293\u53d6\u7a33\u5b9a\u6027\u8f83\u4f4e"
ZH_LOW_INFO_RISK = "\u516c\u5f00\u9875\u9762\u4fe1\u606f\u8f83\u5c11\uff0c\u9700\u8981\u8865\u5145\u4eba\u5de5\u5224\u65ad"
ZH_IG_RISK = "Instagram \u516c\u5f00 HTML \u672a\u66b4\u9732\u6709\u6548\u4e3b\u9875\u5185\u5bb9\uff0c\u5efa\u8bae\u4f7f\u7528 Playwright manual verification \u6216\u5df2\u767b\u5f55 session"
ZH_GENERIC_SUMMARY = "\u8be5\u8fbe\u4eba\u7684\u516c\u5f00\u4e3b\u9875\u4fe1\u606f\u76ee\u524d\u8f83\u6709\u9650\uff0c\u6682\u53ef\u4f5c\u4e3a\u901a\u7528\u751f\u6d3b\u65b9\u5f0f\u6216\u5185\u5bb9\u521b\u4f5c\u7c7b\u5019\u9009\u4eba\u8fdb\u884c\u521d\u6b65\u89c2\u5bdf\u3002\u6b63\u5f0f\u5408\u4f5c\u524d\u5efa\u8bae\u7ee7\u7eed\u4eba\u5de5\u590d\u6838\u5185\u5bb9\u8c03\u6027\u3001\u4e92\u52a8\u8d28\u91cf\u548c\u5546\u4e1a\u5408\u4f5c\u8bb0\u5f55\u3002"
ZH_DANCE_SUMMARY = "\u8be5\u8fbe\u4eba\u5185\u5bb9\u4ee5\u821e\u8e48\u3001\u7f16\u821e/\u7ffb\u8df3\u3001\u7a7f\u642d\u548c\u65e5\u5e38\u5206\u4eab\u4e3a\u4e3b\uff0c\u9002\u5408\u5e74\u8f7b\u5316\u3001\u65f6\u5c1a\u3001\u821e\u8e48\u6216\u751f\u6d3b\u65b9\u5f0f\u7c7b\u54c1\u724c\u8fdb\u5165\u521d\u7b5b\u3002\u7531\u4e8e\u7ed3\u679c\u6765\u81ea\u516c\u5f00\u9875\u9762\u6293\u53d6\uff0c\u6b63\u5f0f\u5f55\u7528\u524d\u4ecd\u9700\u4eba\u5de5\u590d\u6838\u4e92\u52a8\u8d28\u91cf\u3001\u8bc4\u8bba\u533a\u98ce\u9669\u548c\u5546\u4e1a\u5408\u4f5c\u8bb0\u5f55\u3002"
ZH_EDUCATION_SUMMARY = "\u8be5\u8fbe\u4eba\u5177\u6709\u4f20\u5a92\u5927\u5b66\u8001\u5e08\u3001\u5a31\u4e50\u516c\u53f8\u987e\u95ee\u548c\u5185\u5bb9\u521b\u4f5c\u8005\u80cc\u666f\uff0c\u5185\u5bb9\u4e3b\u8981\u56f4\u7ed5\u5927\u5b66\u751f\u751f\u6d3b\u3001\u6821\u56ed\u89c2\u5bdf\u3001\u4eba\u60c5\u4e16\u6545\u3001\u804c\u573a/\u6821\u56ed\u60c5\u5883\u548c\u77ed\u5267\u60c5\u5c55\u5f00\uff0c\u5177\u6709\u8f83\u5f3a\u7684\u5e74\u8f7b\u4eba\u5171\u9e23\u548c\u8bdd\u9898\u4f20\u64ad\u5c5e\u6027\u3002\u9002\u5408\u6559\u80b2\u4ea7\u54c1\u3001\u6821\u56ed\u8425\u9500\u3001\u804c\u4e1a\u6210\u957f\u3001\u5185\u5bb9\u521b\u4f5c\u5de5\u5177\u3001\u77e5\u8bc6\u670d\u52a1\u7c7b\u54c1\u724c\u8fdb\u884c\u521d\u7b5b\u3002\u6b63\u5f0f\u5408\u4f5c\u524d\u5efa\u8bae\u7ee7\u7eed\u4eba\u5de5\u590d\u6838\u8bc4\u8bba\u533a\u6c1b\u56f4\u3001\u5546\u4e1a\u5408\u4f5c\u5386\u53f2\u548c\u5185\u5bb9\u8c03\u6027\u7a33\u5b9a\u6027\u3002"
GENERIC_INTERNAL_TAGS = {
    "\u5185\u5bb9\u53ef\u7ed3\u6784\u5316\u5206\u6790",
    "\u53ef\u8fdb\u5165 brief matching \u521d\u7b5b",
    "\u516c\u5f00\u4fe1\u606f\u6293\u53d6\u98ce\u9669\u8f83\u4f4e",
}


async def analyze_with_llm(scrape: ScrapeResult, brand_brief: str | None = None) -> CreatorAnalysis:
    source = get_analysis_source()
    payload = {
        "platform": scrape.platform,
        "profile_url": scrape.profile_url,
        "nickname": infer_nickname(scrape),
        "bio": scrape.profile_bio or scrape.meta_description,
        "follower_count": scrape.follower_count or infer_follower_count(scrape.meta_description),
        "title": scrape.title,
        "meta_description": scrape.meta_description,
        "visible_text": scrape.visible_text,
        "profile_bio": scrape.profile_bio,
        "following_count": scrape.following_count,
        "follower_count": scrape.follower_count,
        "likes_and_collections_count": scrape.likes_and_collections_count,
        "recent_post_titles": scrape.recent_post_titles,
        "recent_post_links": scrape.recent_post_links,
        "brand_brief": brand_brief or "",
        "detection_reasons": scrape.detection_reasons,
    }

    if source == "mock":
        return mock_analyze(scrape, brand_brief)
    if source == "rule_based":
        return rule_based_analyze(scrape, brand_brief)

    raw = await _call_openai_compatible_llm(payload, brand_brief)
    analysis = CreatorAnalysis.model_validate(_extract_json(raw))
    return apply_extracted_profile_overrides(analysis, scrape, brand_brief, preserve_llm_analysis=True)


def get_analysis_source() -> str:
    if get_env_flag("USE_MOCK_ANALYZER"):
        return "mock"
    if get_llm_api_key():
        return "llm"
    return "rule_based"


def get_llm_provider() -> str:
    if not get_llm_api_key():
        return "none"
    base_url = normalize_base_url(get_llm_base_url()).lower()
    if "deepseek" in base_url:
        return "deepseek"
    return "openai"


def get_analyzer_metadata() -> dict[str, Any]:
    api_key_detected = bool(get_llm_api_key())
    return {
        "analysis_source": get_analysis_source(),
        "llm_provider": get_llm_provider(),
        "llm_model": get_llm_model() if api_key_detected else "",
        "api_key_detected": api_key_detected,
    }


async def _call_openai_compatible_llm(raw_data: dict[str, Any], brand_brief: str | None) -> str:
    base_url = normalize_base_url(get_llm_base_url())
    model = get_llm_model()
    api_key = get_llm_api_key()
    prompt = USER_PROMPT_TEMPLATE.format(
        brand_brief=brand_brief or "\u65e0\u7279\u5b9a brand brief\uff0c\u8bf7\u505a\u901a\u7528\u8fbe\u4eba\u753b\u50cf\u5206\u6790\u3002",
        raw_data=json.dumps(raw_data, ensure_ascii=False)[:14000],
    )

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def normalize_base_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    suffix = "/chat/completions"
    if cleaned.endswith(suffix):
        cleaned = cleaned[: -len(suffix)]
    return cleaned.rstrip("/")


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def mock_analyze(scrape: ScrapeResult, brand_brief: str | None = None) -> CreatorAnalysis:
    return rule_based_analyze(scrape, brand_brief)


def rule_based_analyze(scrape: ScrapeResult, brand_brief: str | None = None) -> CreatorAnalysis:
    text = " ".join(
        [
            scrape.title,
            scrape.meta_description,
            scrape.visible_text,
            scrape.profile_bio,
            " ".join(scrape.recent_post_titles),
        ]
    ).lower()
    categories = infer_categories(text, scrape.platform)
    risk_flags = infer_risks(scrape)

    return CreatorAnalysis(
        platform=scrape.platform,
        profile_url=scrape.profile_url,
        nickname=infer_nickname(scrape),
        bio=scrape.profile_bio or scrape.meta_description or ZH_PUBLIC_BIO_MISSING,
        follower_count=scrape.follower_count or infer_follower_count(scrape.meta_description),
        content_categories=categories,
        recent_post_titles=scrape.recent_post_titles,
        recent_post_links=scrape.recent_post_links,
        brand_fit_tags=infer_brand_fit_tags(text, scrape.platform, brand_brief),
        risk_flags=risk_flags,
        summary=infer_summary(categories),
    )


def apply_extracted_profile_overrides(
    analysis: CreatorAnalysis,
    scrape: ScrapeResult,
    brand_brief: str | None,
    preserve_llm_analysis: bool = False,
) -> CreatorAnalysis:
    text = " ".join([scrape.profile_bio, " ".join(scrape.recent_post_titles), scrape.visible_text]).lower()
    if scrape.profile_bio:
        analysis.bio = scrape.profile_bio
    if scrape.follower_count:
        analysis.follower_count = scrape.follower_count
    analysis.recent_post_titles = scrape.recent_post_titles
    if scrape.recent_post_links is not None:
        analysis.recent_post_links = scrape.recent_post_links
    analysis.brand_fit_tags = remove_generic_tags(analysis.brand_fit_tags)
    analysis.risk_flags = remove_follower_size_risks(analysis.risk_flags)
    if preserve_llm_analysis:
        if not analysis.content_categories:
            analysis.content_categories = infer_categories(text, scrape.platform)
        if not analysis.brand_fit_tags:
            analysis.brand_fit_tags = infer_brand_fit_tags(text, scrape.platform, brand_brief)
        if not analysis.summary or contains_generic_summary(analysis.summary):
            analysis.summary = infer_summary(analysis.content_categories)
        return analysis
    if scrape.platform == "xiaohongshu":
        analysis.content_categories = infer_categories(text, scrape.platform)
        analysis.brand_fit_tags = infer_brand_fit_tags(text, scrape.platform, brand_brief)
        analysis.summary = infer_summary(analysis.content_categories)
    return analysis


def infer_categories(text: str, platform_name: str = "") -> list[str]:
    categories: list[str] = []
    if any(word in text for word in ["\u5927\u5b66\u751f", "\u9ad8\u6821", "\u4f20\u5a92\u5927\u5b66", "\u6559\u80b2\u535a\u4e3b", "\u8001\u5e08", "\u8bba\u6587"]):
        categories.append(ZH_EDUCATION)
    if any(word in text for word in ["\u5927\u5b66\u751f", "\u5927\u56db", "\u5b9e\u4e60\u751f", "\u751f\u6d3b\u5e38\u8bc6\u8bfe"]):
        categories.append(ZH_COLLEGE_CONTENT)
    if any(word in text for word in ["\u6821\u56ed", "\u9ad8\u6821", "\u5927\u5b66", "\u8001\u5e08", "\u4ee3\u8bfe"]):
        categories.append(ZH_CAMPUS_CONTENT)
    if any(word in text for word in ["\u804c\u573a", "\u8f9e\u804c", "\u516c\u53f8", "\u5b9e\u4e60", "\u4eba\u60c5\u4e16\u6545", "\u60c5\u5546"]):
        categories.append(ZH_WORKPLACE_CAMPUS)
    if any(word in text for word in ["\u5f53\u6211", "\u5047\u5982", "\u77ed\u5267", "\u6bb5\u5b50", "\u5927\u6bd4\u62fc", "\u62cd\u89c6\u9891"]):
        categories.append(ZH_SHORT_SKIT)
    if any(word in text for word in ["\u5a31\u4e50", "\u660e\u661f", "\u6f14\u5531\u4f1a", "\u6625\u665a", "\u5185\u5bb9\u521b\u4f5c\u8005"]):
        categories.append(ZH_ENTERTAINMENT)
    if any(word in text for word in ["dance", "dancer", "\u821e\u8e48"]):
        categories.append(ZH_DANCE)
    if any(word in text for word in ["choreo", "\u7f16\u821e", "\u7ffb\u8df3", "\u955c\u9762"]):
        categories.append(ZH_CHOREO)
    if any(word in text for word in ["fashion", "outfit", "\u7a7f\u642d", "\u670d\u9970"]):
        categories.append(ZH_FASHION)
    if any(word in text for word in ["food", "recipe", "\u9910\u996e", "\u7f8e\u98df"]):
        categories.append(ZH_FOOD)
    if any(word in text for word in ["travel", "hotel", "\u65c5\u884c", "\u65c5\u6e38"]):
        categories.append(ZH_TRAVEL)
    if any(word in text for word in ["fitness", "sport", "\u8fd0\u52a8", "\u5065\u8eab"]):
        categories.append(ZH_FITNESS)
    if platform_name == "xiaohongshu" or any(word in text for word in ["daily", "\u65e5\u5e38", "\u751f\u6d3b"]):
        categories.append(ZH_LIFESTYLE)
    return dedupe(categories) or [ZH_LIFESTYLE]


def infer_brand_fit_tags(text: str, platform_name: str, brand_brief: str | None) -> list[str]:
    tags: list[str] = []
    if any(word in text for word in ["\u5927\u5b66\u751f", "\u5927\u56db", "\u5b9e\u4e60\u751f"]):
        tags.append(ZH_COLLEGE_AUDIENCE_TAG)
    if any(word in text for word in ["\u6821\u56ed", "\u9ad8\u6821", "\u5927\u5b66", "\u8001\u5e08"]):
        tags.append(ZH_CAMPUS_TAG)
    if any(word in text for word in ["\u6559\u80b2", "\u8001\u5e08", "\u751f\u6d3b\u5e38\u8bc6\u8bfe", "\u8bba\u6587"]):
        tags.append(ZH_EDUCATION_TAG)
    if any(word in text for word in ["\u804c\u573a", "\u8f9e\u804c", "\u516c\u53f8", "\u5b9e\u4e60", "\u4eba\u60c5\u4e16\u6545"]):
        tags.append(ZH_WORKPLACE_TOPIC_TAG)
    if any(word in text for word in ["\u5f53\u6211", "\u5047\u5982", "\u77ed\u5267", "\u6bb5\u5b50", "\u62cd\u89c6\u9891"]):
        tags.append(ZH_SHORT_SKIT_TAG)
    if any(word in text for word in ["\u5927\u5b66\u751f", "\u60c5\u5546", "\u5927\u56db", "\u5b9e\u4e60\u751f", "\u4eba\u60c5\u4e16\u6545"]):
        tags.append(ZH_YOUNG_EMOTION_TAG)
    if ZH_CAMPUS_TAG in tags or ZH_COLLEGE_AUDIENCE_TAG in tags:
        tags.append(ZH_CAMPUS_MARKETING_TAG)
    if ZH_EDUCATION_TAG in tags:
        tags.append(ZH_EDU_PRODUCT_TAG)
    if any(word in text for word in ["AI", "ai", "\u5185\u5bb9\u521b\u4f5c", "\u62cd\u89c6\u9891", "\u8bba\u6587"]):
        tags.append(ZH_CREATOR_TOOL_TAG)
    if any(word in text for word in ["dance", "dancer", "\u821e\u8e48", "\u7f16\u821e", "\u7ffb\u8df3"]):
        tags.append(ZH_DANCE_TAG)
    if any(word in text for word in ["\u5c0f\u5973\u5b69", "\u8001\u5a46", "girl", "female", "\u5973\u6027"]):
        tags.append(ZH_YOUNG_FEMALE_TAG)
    if any(word in text for word in ["fashion", "outfit", "\u7a7f\u642d", "\u670d\u9970"]):
        tags.append(ZH_OUTFIT_TAG)
    if platform_name in {"xiaohongshu", "douyin", "tiktok"}:
        tags.append(ZH_SHORT_VIDEO_TAG)
    return dedupe(tags)


def infer_summary(categories: list[str]) -> str:
    if ZH_EDUCATION in categories or ZH_COLLEGE_CONTENT in categories or ZH_CAMPUS_CONTENT in categories:
        return ZH_EDUCATION_SUMMARY
    if ZH_DANCE in categories or ZH_CHOREO in categories:
        return ZH_DANCE_SUMMARY
    return ZH_GENERIC_SUMMARY


def infer_risks(scrape: ScrapeResult) -> list[str]:
    risk_flags = []
    if scrape.manual_verification_required:
        risk_flags.append(ZH_MANUAL_RISK)
    if len(scrape.visible_text) < 300 and not scrape.meta_description and not scrape.profile_bio:
        risk_flags.append(ZH_LOW_INFO_RISK)
    if scrape.platform == "instagram" and not scrape.meta_description:
        risk_flags.append(ZH_IG_RISK)
    return risk_flags


def infer_nickname(scrape: ScrapeResult) -> str:
    title = scrape.title.strip()
    if scrape.platform == "xiaohongshu" and title:
        return re.sub(r"\s*[-|_]\s*\u5c0f\u7ea2\u4e66.*$", "", title).strip() or title
    if scrape.platform == "instagram":
        username = extract_username(scrape.profile_url)
        if title and title.lower() != "instagram":
            handle_match = re.search(r"\(@([^)\s]+)\)", title)
            if handle_match:
                return f"@{handle_match.group(1)}"
            return title
        if username:
            return f"@{username}"
    return title or extract_username(scrape.profile_url) or "unknown"


def extract_username(profile_url: str) -> str:
    path_parts = [part for part in urlparse(profile_url).path.split("/") if part]
    if path_parts[:2] == ["user", "profile"] and len(path_parts) >= 3:
        return path_parts[2]
    if path_parts:
        return path_parts[0]
    return ""


def infer_follower_count(meta_description: str) -> str:
    patterns = [
        r"([\d.,]+\s*[kKmMbB]?)\s+followers",
        r"([\d.]+\s*\u4e07\+?)\s*\u4f4d?\u7c89\u4e1d",
        r"([\d,]+\+?)\s*\u4f4d?\u7c89\u4e1d",
    ]
    for pattern in patterns:
        match = re.search(pattern, meta_description, flags=re.IGNORECASE)
        if match:
            return match.group(1).replace(" ", "")
    return "unknown"


def remove_generic_tags(tags: list[str]) -> list[str]:
    return [tag for tag in dedupe(tags) if tag not in GENERIC_INTERNAL_TAGS]


def remove_follower_size_risks(risk_flags: list[str]) -> list[str]:
    follower_terms = [
        "\u7c89\u4e1d\u6570",
        "\u7c89\u4e1d\u91cf",
        "follower count",
        "small following",
        "low follower",
    ]
    return [
        risk
        for risk in risk_flags
        if not any(term.lower() in risk.lower() for term in follower_terms)
    ]


def contains_generic_summary(summary: str) -> bool:
    generic_markers = [
        "\u57fa\u4e8e\u516c\u5f00\u9875\u9762\u5143\u6570\u636e",
        "\u6700\u5c0f\u5316\u8fbe\u4eba\u753b\u50cf\u5206\u6790",
        "MVP \u6d41\u7a0b\u9a8c\u8bc1",
    ]
    return any(marker in summary for marker in generic_markers)


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
