from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from app.services.scraper import ScrapeResult, detect_platform


AccessStatus = Literal[
    "normal_accessible",
    "login_required",
    "manual_verification_required",
    "captcha_required",
    "blocked_or_rate_limited",
    "empty_or_invalid_profile",
]


@dataclass
class AccessControlResult:
    platform: str
    access_status: AccessStatus
    detection_reasons: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    should_skip_llm: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


LOGIN_KEYWORDS = [
    "\u767b\u5f55",
    "\u8bf7\u767b\u5f55",
    "\u767b\u5f55\u540e\u67e5\u770b",
    "\u6ce8\u518c",
    "login",
    "log in",
    "sign in",
    "signup",
    "sign up",
    "register",
]

CAPTCHA_KEYWORDS = [
    "\u9a8c\u8bc1\u7801",
    "\u5b89\u5168\u9a8c\u8bc1",
    "\u4eba\u673a\u9a8c\u8bc1",
    "\u8bf7\u5b8c\u6210\u9a8c\u8bc1",
    "\u6ed1\u5757\u9a8c\u8bc1",
    "captcha",
    "verification",
    "verify",
    "challenge",
    "robot check",
    "bot detection",
]

BLOCKED_KEYWORDS = [
    "\u8bbf\u95ee\u53d7\u9650",
    "\u8bbf\u95ee\u8fc7\u4e8e\u9891\u7e41",
    "\u8bf7\u7a0d\u540e\u518d\u8bd5",
    "\u98ce\u63a7",
    "\u5f02\u5e38\u8bbf\u95ee",
    "\u64cd\u4f5c\u9891\u7e41",
    "access denied",
    "forbidden",
    "rate limit",
    "too many requests",
    "suspicious activity",
    "please wait a few minutes",
]

PLATFORM_KEYWORDS = {
    "weibo": [
        "sina visitor system",
        "\u5fae\u535a\u8bbf\u5ba2\u7cfb\u7edf",
        "passport.weibo",
        "login.sina",
        "\u8bbf\u95ee\u53d7\u9650",
        "\u767b\u5f55\u540e\u67e5\u770b",
    ],
    "douyin": [
        "\u626b\u7801\u767b\u5f55",
        "\u6296\u97f3\u5b89\u5168\u4e2d\u5fc3",
        "douyin.com/passport",
        "captcha",
        "verify",
        "\u98ce\u63a7",
        "\u8bbf\u95ee\u8fc7\u4e8e\u9891\u7e41",
    ],
    "xiaohongshu": [
        "\u767b\u5f55\u540e\u67e5\u770b\u66f4\u591a",
        "\u9a8c\u8bc1",
        "\u5b89\u5168\u9a8c\u8bc1",
        "xsec_token failure",
        "\u5185\u5bb9\u4e0d\u53ef\u89c1",
        "\u8bf7\u5148\u767b\u5f55",
    ],
    "bilibili": [
        "\u767b\u5f55\u540e\u67e5\u770b",
        "\u8bf7\u5148\u767b\u5f55",
        "\u98ce\u63a7\u6821\u9a8c",
        "\u5b89\u5168\u9a8c\u8bc1",
    ],
    "tiktok": [
        "log in",
        "sign up",
        "challenge",
        "verify",
        "suspicious activity",
        "please wait a few minutes",
        "this page is unavailable",
        "login required",
    ],
    "instagram": [
        "log in",
        "sign up",
        "challenge",
        "verify",
        "suspicious activity",
        "please wait a few minutes",
        "this page is unavailable",
        "login required",
    ],
}

GENERIC_TITLES = {
    "",
    "user",
    "login",
    "log in",
    "\u767b\u5f55",
    "\u6296\u97f3",
    "tiktok",
    "instagram",
    "sina visitor system",
    "\u5fae\u535a\u8bbf\u5ba2\u7cfb\u7edf",
}

SOCIAL_PLATFORMS = {
    "xiaohongshu",
    "weibo",
    "douyin",
    "bilibili",
    "tiktok",
    "instagram",
    "youtube",
}


def detect_access_control(scrape: ScrapeResult) -> AccessControlResult:
    platform = scrape.platform or detect_platform(scrape.profile_url)
    haystack = build_haystack(scrape)

    if scrape.manual_verification_required:
        return AccessControlResult(
            platform=platform,
            access_status="manual_verification_required",
            detection_reasons=["Scraper marked this page as requiring manual verification"],
            matched_keywords=scrape.detection_reasons,
            should_skip_llm=True,
        )

    if scrape.http_status in {401, 403}:
        return blocked_result(platform, "HTTP status indicates forbidden/unauthorized", ["http_status"])
    if scrape.http_status == 429:
        return blocked_result(platform, "HTTP status indicates rate limiting", ["http_status"])

    if platform == "xiaohongshu" and has_public_creator_signals(scrape):
        return AccessControlResult(platform=platform, access_status="normal_accessible")

    captcha_matches = find_keywords(haystack, CAPTCHA_KEYWORDS)
    if captcha_matches:
        return AccessControlResult(
            platform=platform,
            access_status="captcha_required",
            detection_reasons=["CAPTCHA or verification keywords detected"],
            matched_keywords=captcha_matches,
            should_skip_llm=True,
        )

    blocked_matches = find_keywords(haystack, BLOCKED_KEYWORDS)
    platform_matches = find_keywords(haystack, PLATFORM_KEYWORDS.get(platform, []))
    if blocked_matches:
        return blocked_result(platform, "Blocked or rate-limited keywords detected", blocked_matches)

    login_matches = find_keywords(haystack, LOGIN_KEYWORDS)
    if login_matches or platform_matches:
        matched = login_matches + [item for item in platform_matches if item not in login_matches]
        return AccessControlResult(
            platform=platform,
            access_status="login_required",
            detection_reasons=["Login or platform access-control keywords detected"],
            matched_keywords=matched,
            should_skip_llm=True,
        )

    if is_empty_or_invalid_profile(scrape, platform):
        return AccessControlResult(
            platform=platform,
            access_status="empty_or_invalid_profile",
            detection_reasons=["Extracted creator profile is too sparse or generic"],
            matched_keywords=[],
            should_skip_llm=True,
        )

    return AccessControlResult(platform=platform, access_status="normal_accessible")


def has_public_creator_signals(scrape: ScrapeResult) -> bool:
    signals = 0
    title = scrape.title.strip().lower()
    if title and title not in GENERIC_TITLES and title != "小红书":
        signals += 1
    if scrape.profile_bio:
        signals += 1
    if scrape.follower_count and scrape.follower_count != "unknown":
        signals += 1
    if scrape.recent_post_titles:
        signals += 1
    if scrape.meta_description and len(scrape.meta_description.strip()) >= 12:
        signals += 1
    if len(scrape.visible_text.strip()) >= 300:
        signals += 1
    return signals >= 2


def build_haystack(scrape: ScrapeResult) -> str:
    return " ".join(
        [
            scrape.profile_url,
            scrape.title,
            scrape.meta_description,
            scrape.visible_text,
            scrape.profile_bio,
            " ".join(scrape.recent_post_titles),
            " ".join(scrape.recent_post_links),
        ]
    ).lower()


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    matches: list[str] = []
    for keyword in keywords:
        if keyword.lower() in text:
            matches.append(keyword)
    return matches


def blocked_result(platform: str, reason: str, matches: list[str]) -> AccessControlResult:
    return AccessControlResult(
        platform=platform,
        access_status="blocked_or_rate_limited",
        detection_reasons=[reason],
        matched_keywords=matches,
        should_skip_llm=True,
    )


def is_empty_or_invalid_profile(scrape: ScrapeResult, platform: str) -> bool:
    if platform not in SOCIAL_PLATFORMS:
        return False

    weak_signals = 0
    title = scrape.title.strip().lower()
    if title in GENERIC_TITLES:
        weak_signals += 1
    if not scrape.profile_bio and not scrape.meta_description:
        weak_signals += 1
    if not scrape.follower_count or scrape.follower_count == "unknown":
        weak_signals += 1
    if not scrape.recent_post_titles:
        weak_signals += 1
    if len(scrape.visible_text.strip()) < 120 or looks_like_noise_only(scrape.visible_text):
        weak_signals += 1
    if scrape.recent_post_links and links_are_mostly_noise(scrape.recent_post_links):
        weak_signals += 1

    return weak_signals >= 4


def looks_like_noise_only(text: str) -> bool:
    if not text.strip():
        return True
    noise_terms = [
        "\u8425\u4e1a\u6267\u7167",
        "\u6caaICP\u5907",
        "\u516c\u7f51\u5b89\u5907",
        "\u4e3e\u62a5",
        "privacy",
        "terms",
        "copyright",
    ]
    hits = sum(1 for term in noise_terms if term.lower() in text.lower())
    return hits >= 3


def links_are_mostly_noise(links: list[str]) -> bool:
    noisy = 0
    for link in links:
        lowered = link.lower()
        if any(term in lowered for term in ["login", "passport", "beian", "report", "privacy", "terms"]):
            noisy += 1
    return noisy >= max(1, len(links) // 2)


def skipped_creator_from_access(scrape: ScrapeResult, access: AccessControlResult) -> dict:
    return {
        "platform": access.platform,
        "profile_url": scrape.profile_url,
        "nickname": "",
        "bio": "",
        "follower_count": scrape.follower_count or "unknown",
        "content_categories": [],
        "recent_post_titles": [],
        "recent_post_links": [],
        "brand_fit_tags": [],
        "risk_flags": [
            access.access_status,
            "\u9875\u9762\u672a\u83b7\u53d6\u5230\u6709\u6548\u8fbe\u4eba\u4fe1\u606f\uff0c\u53ef\u80fd\u9700\u8981\u767b\u5f55\u6216\u4eba\u673a\u9a8c\u8bc1",
        ],
        "summary": "\u672a\u80fd\u8bbf\u95ee\u5230\u6709\u6548\u8fbe\u4eba\u4fe1\u606f\uff0c\u8bf7\u5148\u5b8c\u6210\u767b\u5f55\u3001\u9a8c\u8bc1\u6216\u4eba\u5de5\u590d\u6838\u540e\u518d\u8fdb\u884c\u5206\u6790\u3002",
    }
