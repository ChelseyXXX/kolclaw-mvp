from __future__ import annotations

import asyncio
import html
import platform
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


def configure_windows_event_loop_policy() -> None:
    """Use the Windows loop policy that supports subprocesses before Playwright starts."""
    if platform.system() != "Windows":
        return
    proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if proactor_policy is not None:
        asyncio.set_event_loop_policy(proactor_policy())


configure_windows_event_loop_policy()


LOGIN_OR_CAPTCHA_PATTERNS = [
    r"\blog\s*in\b",
    r"\bsign\s*in\b",
    r"captcha",
    r"verify you are human",
    "\u4eba\u673a\u9a8c\u8bc1",
    "\u9a8c\u8bc1\u7801",
    "\u767b\u5f55",
]

XHS_NOISE_TERMS = [
    "\u53d1\u73b0",
    "\u76f4\u64ad",
    "\u53d1\u5e03",
    "\u901a\u77e5",
    "\u521b\u4f5c\u4e2d\u5fc3",
    "\u4e1a\u52a1\u5408\u4f5c",
    "\u5173\u6ce8",
    "\u7c89\u4e1d",
    "\u83b7\u8d5e\u4e0e\u6536\u85cf",
    "\u7b14\u8bb0",
    "\u6536\u85cf",
    "\u7f6e\u9876",
    "\u52a0\u8f7d\u4e2d",
    "\u66f4\u591a",
    "\u6caaICP\u5907",
    "\u8425\u4e1a\u6267\u7167",
    "\u516c\u7f51\u5b89\u5907",
    "\u589e\u503c\u7535\u4fe1\u4e1a\u52a1\u7ecf\u8425\u8bb8\u53ef\u8bc1",
    "\u533b\u7597\u5668\u68b0",
    "\u4e92\u8054\u7f51\u836f\u54c1",
    "\u4e3e\u62a5",
    "\u4e0a\u6d77\u5e02\u4e92\u8054\u7f51\u4e3e\u62a5\u4e2d\u5fc3",
    "\u7f51\u4e0a\u6709\u5bb3\u4fe1\u606f\u4e3e\u62a5\u4e13\u533a",
    "\u81ea\u8425\u7ecf\u8425\u8005\u4fe1\u606f",
    "\u7f51\u7edc\u6587\u5316\u7ecf\u8425\u8bb8\u53ef\u8bc1",
    "\u4e2a\u6027\u5316\u63a8\u8350\u7b97\u6cd5",
    "\u7f51\u4fe1\u7b97\u5907",
    "\u884c\u541f\u4fe1\u606f\u79d1\u6280",
    "\u5730\u5740",
    "\u7535\u8bdd",
    "USER_FEEDS_LAYOUT_PLACEHOLDER",
]

XHS_VALUE_PATTERN = r"\d+(?:\.\d+)?(?:\u4e07)?\+?"

XHS_BIO_NOISE_TERMS = [
    "\u53d1\u73b0",
    "\u76f4\u64ad",
    "\u53d1\u5e03",
    "\u901a\u77e5",
    "\u521b\u4f5c\u4e2d\u5fc3",
    "\u4e1a\u52a1\u5408\u4f5c",
    "\u6caaICP\u5907",
    "\u8425\u4e1a\u6267\u7167",
    "\u516c\u7f51\u5b89\u5907",
    "\u589e\u503c\u7535\u4fe1\u4e1a\u52a1\u7ecf\u8425\u8bb8\u53ef\u8bc1",
    "\u533b\u7597\u5668\u68b0",
    "\u4e92\u8054\u7f51\u836f\u54c1",
    "\u4e3e\u62a5",
    "\u7f51\u4e0a\u6709\u5bb3\u4fe1\u606f\u4e3e\u62a5\u4e13\u533a",
    "USER_FEEDS_LAYOUT_PLACEHOLDER",
]

LEGAL_OR_REPORT_DOMAINS = [
    "shjbzx.cn",
    "12377.cn",
    "beian.gov.cn",
    "beian.miit.gov.cn",
]


@dataclass
class ScrapeResult:
    platform: str
    profile_url: str
    title: str = ""
    meta_description: str = ""
    visible_text: str = ""
    profile_bio: str = ""
    following_count: str = ""
    follower_count: str = ""
    likes_and_collections_count: str = ""
    recent_post_titles: list[str] = field(default_factory=list)
    recent_post_links: list[str] = field(default_factory=list)
    manual_verification_required: bool = False
    detection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram" in host:
        return "instagram"
    if "tiktok" in host:
        return "tiktok"
    if "youtube" in host:
        return "youtube"
    if "xiaohongshu" in host or "xhslink" in host:
        return "xiaohongshu"
    if "douyin" in host:
        return "douyin"
    if "bilibili" in host:
        return "bilibili"
    return "website"


def detect_manual_verification(text: str) -> list[str]:
    lowered = text.lower()
    return [
        pattern
        for pattern in LOGIN_OR_CAPTCHA_PATTERNS
        if re.search(pattern, lowered, flags=re.IGNORECASE)
    ]


def compact_text(text: str, max_chars: int = 12000) -> str:
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", text)
    cleaned = re.sub(r"\n\s*", "\n", cleaned).strip()
    return cleaned[:max_chars]


def compact_inline_text(text: str, max_chars: int = 12000) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:max_chars]


def has_useful_public_metadata(title: str, meta_description: str) -> bool:
    text = " ".join([title, meta_description]).strip()
    return len(text) >= 12 and text.lower() not in {"instagram", "xiaohongshu", "\u5c0f\u7ea2\u4e66"}


def should_skip_playwright_for_runtime(manual_verification: bool) -> bool:
    return (
        not manual_verification
        and platform.system() == "Windows"
        and sys.version_info >= (3, 14)
    )


async def scrape_profile(
    profile_url: str,
    manual_verification: bool = False,
    manual_timeout_seconds: int = 180,
) -> ScrapeResult:
    if should_skip_playwright_for_runtime(manual_verification):
        return scrape_profile_with_urllib(profile_url)

    configure_windows_event_loop_policy()
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        if manual_verification:
            raise RuntimeError(
                "Playwright is required for manual verification mode. Run "
                "`pip install -r requirements.txt` and "
                "`python -m playwright install chromium`."
            ) from exc
        return scrape_profile_with_urllib(profile_url)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=not manual_verification)
            context = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)

            title, meta_description, visible_text = await _extract_page_text(page)
            reasons = detect_manual_verification(" ".join([title, meta_description]))

            if reasons and manual_verification:
                print(
                    "Manual verification required. Complete login/CAPTCHA in the "
                    "browser, then press Enter here to resume extraction."
                )
                await asyncio.to_thread(input)
                await page.wait_for_timeout(1000)
                title, meta_description, visible_text = await _extract_page_text(page)
                reasons = detect_manual_verification(" ".join([title, meta_description]))

            link_pairs = await _extract_recent_link_pairs(page)
            await browser.close()
    except Exception as exc:
        if manual_verification:
            raise RuntimeError(
                "Playwright failed during manual verification mode. On Windows, "
                "prefer Python 3.11 or 3.12 and run "
                "`python -m playwright install chromium`."
            ) from exc
        return scrape_profile_with_urllib(profile_url)

    platform_name = detect_platform(profile_url)
    filtered_links = filter_recent_links(link_pairs, profile_url, platform_name)
    result = ScrapeResult(
        platform=platform_name,
        profile_url=profile_url,
        title=title,
        meta_description=meta_description,
        visible_text=compact_text(visible_text),
        recent_post_titles=[item[0] for item in filtered_links],
        recent_post_links=[item[1] for item in filtered_links],
        manual_verification_required=bool(reasons),
        detection_reasons=reasons,
    )
    enrich_platform_extraction(result, visible_text)
    return result


def scrape_profile_with_urllib(profile_url: str) -> ScrapeResult:
    request = urllib.request.Request(
        profile_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw_html = response.read().decode(charset, errors="replace")

    parser = SimpleHTMLExtractor()
    parser.feed(raw_html)
    visible_text = compact_text("\n".join(parser.text_parts))
    platform_name = detect_platform(profile_url)
    reasons = detect_manual_verification(" ".join([parser.title, parser.meta_description]))
    if has_useful_public_metadata(parser.title, parser.meta_description):
        reasons = []
    recent_links = filter_recent_links(parser.links, profile_url, platform_name)

    result = ScrapeResult(
        platform=platform_name,
        profile_url=profile_url,
        title=parser.title,
        meta_description=parser.meta_description,
        visible_text=visible_text,
        recent_post_titles=[item[0] for item in recent_links],
        recent_post_links=[item[1] for item in recent_links],
        manual_verification_required=bool(reasons),
        detection_reasons=reasons,
    )
    enrich_platform_extraction(result, visible_text)
    return result


class SimpleHTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._in_title = False
        self._skip_depth = 0
        self._current_href: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            meta_name = attrs_dict.get("name", "").lower()
            meta_property = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "")
            if meta_name == "description" and content:
                self.meta_description = content
            if meta_property == "og:description" and content and not self.meta_description:
                self.meta_description = content
            if meta_name == "twitter:description" and content and not self.meta_description:
                self.meta_description = content
            if meta_property == "og:title" and content and not self.title:
                self.title = content
        if tag == "a" and attrs_dict.get("href"):
            self._current_href = attrs_dict["href"]
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._current_href:
            text = compact_inline_text(" ".join(self._current_link_text), max_chars=120)
            if text:
                self.links.append((text, self._current_href))
            self._current_href = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        if self._current_href:
            self._current_link_text.append(text)
        self.text_parts.append(text)


def enrich_platform_extraction(result: ScrapeResult, raw_visible_text: str) -> None:
    if result.platform != "xiaohongshu":
        return
    profile = extract_xhs_profile(raw_visible_text, result.title)
    result.profile_bio = profile.get("bio", "")
    result.following_count = profile.get("following_count", "")
    result.follower_count = profile.get("follower_count", "")
    result.likes_and_collections_count = profile.get("likes_and_collections_count", "")
    post_titles = extract_xhs_post_titles(raw_visible_text, profile.get("nickname", ""))
    if post_titles:
        result.recent_post_titles = post_titles
    result.recent_post_links = [
        link
        for link in result.recent_post_links
        if is_real_xhs_note_url(link) and not contains_legal_or_report_domain(link)
    ]


def extract_xhs_profile(text: str, title: str = "") -> dict[str, str]:
    lines = normalized_lines(text)
    nickname = extract_xhs_nickname(title)
    stats = extract_xhs_stats(text)
    stats_index = find_xhs_stats_start(lines)
    bio = extract_xhs_bio(lines, stats_index, nickname)
    if not bio:
        bio = extract_xhs_bio_from_compact_text(text)
    return {
        "nickname": nickname,
        "bio": bio,
        "following_count": stats.get("following_count", ""),
        "follower_count": stats.get("follower_count", ""),
        "likes_and_collections_count": stats.get("likes_and_collections_count", ""),
    }


def extract_xhs_nickname(title: str) -> str:
    return re.sub(r"\s*[-|_]\s*\u5c0f\u7ea2\u4e66.*$", "", title.strip()).strip()


def extract_xhs_stats(text: str) -> dict[str, str]:
    stats = {
        "following_count": "",
        "follower_count": "",
        "likes_and_collections_count": "",
    }
    header_text = extract_xhs_header_text(text)
    triple_pattern = (
        rf"(?P<following>{XHS_VALUE_PATTERN})\s*\u5173\u6ce8\s*"
        rf"(?P<follower>{XHS_VALUE_PATTERN})\s*\u7c89\u4e1d\s*"
        rf"(?P<likes>{XHS_VALUE_PATTERN})\s*\u83b7\u8d5e\u4e0e\u6536\u85cf"
    )
    match = re.search(triple_pattern, header_text)
    if match:
        stats["following_count"] = match.group("following")
        stats["follower_count"] = match.group("follower")
        stats["likes_and_collections_count"] = match.group("likes")
    return stats


def extract_xhs_header_text(text: str) -> str:
    lines = normalized_lines(text)
    stop_index = len(lines)
    for index, line in enumerate(lines):
        if line in {"\u7b14\u8bb0", "\u6536\u85cf", "\u7f6e\u9876"}:
            stop_index = index
            break
    return compact_inline_text(" ".join(lines[:stop_index]))


def extract_xhs_bio(lines: list[str], stats_index: int, nickname: str) -> str:
    if stats_index <= 0:
        return ""
    start = 0
    for index, line in enumerate(lines[:stats_index]):
        if (
            "\u5c0f\u7ea2\u4e66\u53f7" in line
            or "IP\u5c5e\u5730" in line
            or line == nickname
        ):
            start = index + 1
    candidates = [
        line
        for line in lines[start:stats_index]
        if is_xhs_bio_line(line, nickname)
    ]
    return compact_inline_text(" ".join(candidates), max_chars=500)


def extract_xhs_bio_from_compact_text(text: str) -> str:
    compact = compact_inline_text(text, max_chars=5000)
    marker_pattern = (
        r"(?:\u5c0f\u7ea2\u4e66\u53f7[:\uff1a]?\s*[A-Za-z0-9_.-]+\s*)?"
        r"(?:IP\u5c5e\u5730[:\uff1a]?\s*[\u4e00-\u9fffA-Za-z]+\s*)?"
        r"(?P<bio>.+?)"
        r"\s*[\d.]+\s*\u4e07?\+?\s*\u5173\u6ce8\s*"
        r"[\d.]+\s*\u4e07?\+?\s*\u7c89\u4e1d\s*"
        r"[\d.]+\s*\u4e07?\+?\s*\u83b7\u8d5e\u4e0e\u6536\u85cf"
    )
    match = re.search(marker_pattern, compact)
    if not match:
        return ""
    bio = match.group("bio")
    for term in ["\u5c0f\u7ea2\u4e66\u53f7", "IP\u5c5e\u5730"]:
        if term in bio:
            bio = bio.split(term)[-1]
    return compact_inline_text(bio, max_chars=500)


def is_xhs_bio_line(line: str, nickname: str) -> bool:
    if not line or line == nickname:
        return False
    if "\u5c0f\u7ea2\u4e66\u53f7" in line or "IP\u5c5e\u5730" in line:
        return False
    if any(term in line for term in XHS_BIO_NOISE_TERMS):
        return False
    if contains_legal_or_report_domain(line):
        return False
    if re.fullmatch(r"[\d.]+\s*\u4e07?\+?", line):
        return False
    return True


def extract_xhs_post_titles(text: str, nickname: str) -> list[str]:
    lines = normalized_lines(text)
    stats_index = find_xhs_stats_start(lines)
    start = stats_index + 1 if stats_index >= 0 else 0
    titles: list[str] = []
    seen: set[str] = set()
    for line in lines[start:]:
        title = compact_inline_text(line, max_chars=120)
        if is_noise_title(title, nickname):
            continue
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
        if len(titles) >= 12:
            break
    return titles


def find_xhs_stats_start(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if "\u5173\u6ce8" in line and "\u7c89\u4e1d" in line:
            return index
        if re.fullmatch(XHS_VALUE_PATTERN, line):
            window = " ".join(lines[index : index + 6])
            if "\u5173\u6ce8" in window and "\u7c89\u4e1d" in window:
                return index
    return -1


def normalized_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        normalized = re.sub(
            rf"({XHS_VALUE_PATTERN}\s*(?:\u5173\u6ce8|\u7c89\u4e1d|\u83b7\u8d5e\u4e0e\u6536\u85cf))",
            r"\n\1\n",
            normalized,
        )
    return [compact_inline_text(line) for line in normalized.split("\n") if compact_inline_text(line)]


def is_noise_title(title: str, nickname: str = "") -> bool:
    if not title:
        return True
    if nickname and title == nickname:
        return True
    if any(term in title for term in XHS_NOISE_TERMS):
        return True
    if contains_legal_or_report_domain(title):
        return True
    if re.fullmatch(r"[\d.,]+(?:\.\d+)?(?:\u4e07)?\+?", title):
        return True
    if re.fullmatch(r"[\d.,]+\s*(?:likes?|comments?|\u8d5e|\u8bc4\u8bba|\u6536\u85cf)", title, re.IGNORECASE):
        return True
    if title.startswith("http://") or title.startswith("https://") or title.startswith("//"):
        return True
    return False


def filter_recent_links(
    links: list[tuple[str, str]],
    profile_url: str,
    platform_name: str | None = None,
) -> list[tuple[str, str]]:
    filtered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, href in links:
        absolute_href = urljoin(profile_url, href)
        if absolute_href in seen or absolute_href == profile_url:
            continue
        if href == "#" or contains_legal_or_report_domain(absolute_href):
            continue
        if platform_name == "xiaohongshu" and not is_real_xhs_note_url(absolute_href):
            continue
        if is_noise_title(title):
            continue
        seen.add(absolute_href)
        filtered.append((title, absolute_href))
        if len(filtered) >= 10:
            break
    return filtered


def contains_legal_or_report_domain(value: str) -> bool:
    lowered = value.lower()
    return any(domain in lowered for domain in LEGAL_OR_REPORT_DOMAINS)


def is_real_xhs_note_url(url: str) -> bool:
    parsed = urlparse(urljoin("https://www.xiaohongshu.com", url))
    host = parsed.netloc.lower()
    if "xiaohongshu.com" not in host and "xhslink.com" not in host:
        return False
    path = parsed.path.lower()
    return bool(
        re.fullmatch(r"/explore/[0-9a-z]+", path)
        or re.fullmatch(r"/discovery/item/[0-9a-z]+", path)
        or re.fullmatch(r"/search_result/[0-9a-z]+", path)
    )


async def _extract_page_text(page) -> tuple[str, str, str]:
    title = await page.title()
    meta_description = await page.locator("meta[name='description']").first.get_attribute("content")
    visible_text = await page.locator("body").inner_text(timeout=10000)
    return title or "", meta_description or "", visible_text or ""


async def _extract_recent_link_pairs(page) -> list[tuple[str, str]]:
    links = await page.locator("a").evaluate_all(
        """nodes => nodes.slice(0, 120).map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))"""
    )
    pairs: list[tuple[str, str]] = []
    for link in links:
        text = compact_inline_text(link.get("text", ""), max_chars=120)
        href = link.get("href", "")
        if href:
            pairs.append((text or href, href))
    return pairs
