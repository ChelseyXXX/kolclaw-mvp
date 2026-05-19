from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

from app.db import get_connection, init_db, save_creator_analysis
from app.llm import (
    get_analyzer_metadata,
    infer_follower_count,
    infer_nickname,
    mock_analyze,
    normalize_base_url,
)
from app.matcher import match_brief
from app.schemas import CreatorAnalysis
from app.schemas import AnalyzeProfileRequest
from app.scraper import (
    ScrapeResult,
    SimpleHTMLExtractor,
    detect_manual_verification,
    enrich_platform_extraction,
    extract_xhs_profile,
)


XHS_VISIBLE_TEXT = """
发现
直播
发布
通知
柠檬00
小红书号：123456789
IP属地：上海
05dancer 🈴私 穿搭舞蹈集一体的小女孩！谢谢老婆们的关注！视频均已镜面❕翻跳记得带#柠檬00编舞～
28
关注
3.6万
粉丝
31.9万
获赞与收藏
笔记
收藏
置顶
柠檬00
舞编成这样能当小县城舞蹈老师吗…？
用宇宙宙歌开启9月！
谁是你的本命！
对这个迷你可爱的小吉他爱不释手！
21🎂
拍到蓝调时刻啦⭐️
好chill的一支舞！
把一千零一夜开头也编啦
一定要看到第五秒！
违法不良信息举报电话：4006676810
网上有害信息举报专区
沪ICP备13030189号
营业执照
"""


REQUIRED_CREATOR_KEYS = [
    "platform",
    "profile_url",
    "nickname",
    "bio",
    "follower_count",
    "content_categories",
    "recent_post_titles",
    "recent_post_links",
    "brand_fit_tags",
    "risk_flags",
    "summary",
]


def test_request_debug_defaults_to_false() -> None:
    request = AnalyzeProfileRequest(profile_url="https://example.com")
    assert request.debug is False


def test_sample_output_matches_required_creator_schema_exactly() -> None:
    sample_path = Path(__file__).resolve().parent.parent / "examples" / "sample_output.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    assert list(sample.keys()) == REQUIRED_CREATOR_KEYS
    assert "raw_extraction" not in sample
    assert "creator" not in sample
    assert "status" not in sample
    assert "\u53ef\u8fdb\u5165 brief matching \u521d\u7b5b" not in sample["brand_fit_tags"]


def test_normalize_base_url_accepts_full_chat_completions_url() -> None:
    assert normalize_base_url("https://api.deepseek.com/chat/completions") == "https://api.deepseek.com"
    assert normalize_base_url("https://api.deepseek.com") == "https://api.deepseek.com"


def test_analyze_profile_default_returns_creator_json_directly() -> None:
    main = importlib.import_module("app.main")
    original_scrape = main.scrape_profile
    original_analyze = main.analyze_with_llm

    async def fake_scrape(url: str, manual_verification: bool = False) -> ScrapeResult:
        return ScrapeResult(platform="website", profile_url=url, title="Example")

    async def fake_analyze(scrape: ScrapeResult, brand_brief: str | None = None) -> CreatorAnalysis:
        return CreatorAnalysis(
            platform=scrape.platform,
            profile_url=scrape.profile_url,
            nickname="Example",
        )

    try:
        main.scrape_profile = fake_scrape
        main.analyze_with_llm = fake_analyze
        response = asyncio.run(
            main.analyze_profile(
                AnalyzeProfileRequest(
                    profile_url="https://example.com",
                    save_to_db=False,
                )
            )
        )
    finally:
        main.scrape_profile = original_scrape
        main.analyze_with_llm = original_analyze

    assert isinstance(response, CreatorAnalysis)
    assert list(response.model_dump().keys()) == REQUIRED_CREATOR_KEYS


def test_analyze_profile_debug_returns_wrapped_response() -> None:
    main = importlib.import_module("app.main")
    original_scrape = main.scrape_profile
    original_analyze = main.analyze_with_llm

    async def fake_scrape(url: str, manual_verification: bool = False) -> ScrapeResult:
        return ScrapeResult(platform="website", profile_url=url, title="Example")

    async def fake_analyze(scrape: ScrapeResult, brand_brief: str | None = None) -> CreatorAnalysis:
        return CreatorAnalysis(platform=scrape.platform, profile_url=scrape.profile_url)

    try:
        main.scrape_profile = fake_scrape
        main.analyze_with_llm = fake_analyze
        response = asyncio.run(
            main.analyze_profile(
                AnalyzeProfileRequest(
                    profile_url="https://example.com",
                    debug=True,
                    save_to_db=False,
                )
            )
        )
    finally:
        main.scrape_profile = original_scrape
        main.analyze_with_llm = original_analyze

    assert response.status == "completed"
    assert response.creator is not None
    assert response.raw_extraction is not None


def test_analyze_profile_manual_verification_response_is_status_object() -> None:
    main = importlib.import_module("app.main")
    original_scrape = main.scrape_profile

    async def fake_scrape(url: str, manual_verification: bool = False) -> ScrapeResult:
        return ScrapeResult(
            platform="website",
            profile_url=url,
            manual_verification_required=True,
        )

    try:
        main.scrape_profile = fake_scrape
        response = asyncio.run(
            main.analyze_profile(
                AnalyzeProfileRequest(
                    profile_url="https://example.com",
                    save_to_db=False,
                )
            )
        )
    finally:
        main.scrape_profile = original_scrape

    assert response.status == "manual_verification_required"
    assert response.manual_verification_required is True
    assert response.raw_extraction is None
    assert response.resume_token


def test_detect_manual_verification_keywords() -> None:
    reasons = detect_manual_verification("Please log in. CAPTCHA required.")
    assert reasons


def test_html_extractor_skips_script_and_style_content() -> None:
    parser = SimpleHTMLExtractor()
    parser.feed(
        """
        <html>
          <head>
            <title>Creator - Xiaohongshu</title>
            <meta name="description" content="Creator has 1万+位粉丝">
            <style>.login { color: red; }</style>
            <script>var css = "Login.123.css";</script>
          </head>
          <body><a href="/note/1">Useful note</a></body>
        </html>
        """
    )
    visible = " ".join(parser.text_parts)
    assert "Login.123.css" not in visible
    assert ".login" not in visible
    assert parser.meta_description == "Creator has 1万+位粉丝"


def test_xiaohongshu_profile_extraction_prefers_visible_profile_section() -> None:
    profile = extract_xhs_profile(XHS_VISIBLE_TEXT, "柠檬00 - 小红书")
    assert profile["nickname"] == "柠檬00"
    assert "05dancer" in profile["bio"]
    assert "穿搭舞蹈" in profile["bio"]
    assert profile["following_count"] == "28"
    assert profile["follower_count"] == "3.6万"
    assert profile["likes_and_collections_count"] == "31.9万"


def test_xiaohongshu_enrichment_filters_noisy_post_titles_and_links() -> None:
    scrape = ScrapeResult(
        platform="xiaohongshu",
        profile_url="https://www.xiaohongshu.com/user/profile/601aa2310000000001008e6a",
        title="柠檬00 - 小红书",
        meta_description="柠檬00在「小红书」上有1万+位粉丝，已关注10+人",
        visible_text=XHS_VISIBLE_TEXT,
        recent_post_titles=["违法不良信息举报电话：4006676810", "网上有害信息举报专区", "置顶", "柠檬00"],
        recent_post_links=[
            "https://www.shjbzx.cn/",
            "https://www.12377.cn/",
            "https://beian.gov.cn/",
            "https://www.xiaohongshu.com/user/profile/601aa2310000000001008e6a",
        ],
    )
    enrich_platform_extraction(scrape, XHS_VISIBLE_TEXT)

    assert scrape.profile_bio
    assert scrape.follower_count == "3.6万"
    assert "违法不良信息举报电话：4006676810" not in scrape.recent_post_titles
    assert "网上有害信息举报专区" not in scrape.recent_post_titles
    assert "置顶" not in scrape.recent_post_titles
    assert "柠檬00" not in scrape.recent_post_titles
    assert "舞编成这样能当小县城舞蹈老师吗…？" in scrape.recent_post_titles
    assert "用宇宙宙歌开启9月！" in scrape.recent_post_titles
    assert all("shjbzx.cn" not in link for link in scrape.recent_post_links)
    assert all("12377.cn" not in link for link in scrape.recent_post_links)
    assert all("beian" not in link for link in scrape.recent_post_links)


def test_xiaohongshu_mock_analysis_uses_profile_bio_stats_and_content_signals() -> None:
    scrape = ScrapeResult(
        platform="xiaohongshu",
        profile_url="https://www.xiaohongshu.com/user/profile/601aa2310000000001008e6a",
        title="柠檬00 - 小红书",
        meta_description="柠檬00在「小红书」上有1万+位粉丝，已关注10+人",
        visible_text=XHS_VISIBLE_TEXT,
    )
    enrich_platform_extraction(scrape, XHS_VISIBLE_TEXT)
    analysis = mock_analyze(scrape, "young sportswear brand")

    assert analysis.nickname == "柠檬00"
    assert "05dancer" in analysis.bio
    assert "穿搭舞蹈" in analysis.bio
    assert analysis.follower_count == "3.6万"
    assert "舞蹈" in analysis.content_categories
    assert "编舞/翻跳" in analysis.content_categories
    assert "时尚穿搭" in analysis.content_categories
    assert "日常生活" in analysis.content_categories
    assert "舞蹈内容" in analysis.brand_fit_tags
    assert "穿搭相关" in analysis.brand_fit_tags


def test_instagram_empty_public_html_gets_username_and_risk() -> None:
    scrape = ScrapeResult(
        platform="instagram",
        profile_url="https://www.instagram.com/chelsey_xue/",
        title="Instagram",
        meta_description="",
        visible_text="",
    )
    analysis = mock_analyze(scrape)
    assert analysis.nickname == "@chelsey_xue"
    assert analysis.risk_flags


def test_follower_count_inference() -> None:
    assert infer_follower_count("Creator has 12.3K Followers") == "12.3K"
    assert infer_follower_count("有1万+位粉丝") == "1万+"


def test_nickname_inference() -> None:
    scrape = ScrapeResult(
        platform="instagram",
        profile_url="https://www.instagram.com/demo_user/",
        title="Instagram",
    )
    assert infer_nickname(scrape) == "@demo_user"


def test_sqlite_save_and_match(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.sqlite3"
    analysis = CreatorAnalysis(
        platform="website",
        profile_url="https://example.com",
        nickname="Example Creator",
        bio="sports and lifestyle content",
        follower_count="unknown",
        content_categories=["运动健康", "日常生活"],
        recent_post_titles=["Light sports outfit"],
        recent_post_links=["https://example.com/post"],
        brand_fit_tags=["适合轻运动品牌"],
        risk_flags=[],
        summary="Creator fits sports and lifestyle briefs.",
    )

    with get_connection(db_path) as conn:
        init_db(conn)
        creator_id = save_creator_analysis(conn, analysis)
        candidates = match_brief(conn, "运动健康生活方式达人", limit=3)

    assert creator_id == 1
    assert candidates
    assert candidates[0].score > 0
    assert candidates[0].profile_url == "https://example.com"


def test_analyzer_metadata_without_api_key_is_rule_based(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("USE_MOCK_ANALYZER", raising=False)
    metadata = get_analyzer_metadata()
    assert metadata["analysis_source"] == "rule_based"
    assert metadata["llm_provider"] == "none"
    assert metadata["api_key_detected"] is False


def test_xiaohongshu_stats_prefers_visible_header_values() -> None:
    visible_text = "\n".join(
        [
            "\u53a8\u5b50\u8001\u5e08\u5085\u82f1\u4fca",
            "\u539f\u4f20\u5a92\u5927\u5b66\u8001\u5e08 \u5a31\u4e50\u516c\u53f8\u987e\u95ee \u5185\u5bb9\u521b\u4f5c\u8005",
            "44",
            "\u5173\u6ce8",
            "45.2\u4e07",
            "\u7c89\u4e1d",
            "537.5\u4e07",
            "\u83b7\u8d5e\u4e0e\u6536\u85cf",
            "\u7b14\u8bb0",
            "\u9ad8\u6821\u8f9e\u804c\u8bb0\u5f55 \u8fd95\u5206\u949f\u5c31\u662f\u6211\u76846\u5e74",
            "\u53a8\u5b50\u8001\u5e08\u5085\u82f1\u4fca",
            "2.4\u4e07",
        ]
    )
    scrape = ScrapeResult(
        platform="xiaohongshu",
        profile_url="https://www.xiaohongshu.com/user/profile/example",
        title="\u53a8\u5b50\u8001\u5e08\u5085\u82f1\u4fca - \u5c0f\u7ea2\u4e66",
        meta_description="\u53a8\u5b50\u8001\u5e08\u5085\u82f1\u4fca\u5728\u300c\u5c0f\u7ea2\u4e66\u300d\u4e0a\u67091\u4e07+\u4f4d\u7c89\u4e1d",
        visible_text=visible_text,
    )
    enrich_platform_extraction(scrape, visible_text)
    creator = mock_analyze(scrape)

    assert scrape.following_count == "44"
    assert scrape.follower_count == "45.2\u4e07"
    assert scrape.likes_and_collections_count == "537.5\u4e07"
    assert creator.follower_count == "45.2\u4e07"


def test_rule_based_analysis_handles_education_campus_creator() -> None:
    titles = [
        "\u9ad8\u6821\u8f9e\u804c\u8bb0\u5f55 \u8fd95\u5206\u949f\u5c31\u662f\u6211\u76846\u5e74",
        "\u5927\u5b66\u751f\u5e94\u8be5\u61c2\u7684\u4eba\u60c5\u4e16\u6545",
        "\u5f53\u6211\u5728\u516c\u53f8\u4e3e\u529e\u4e86\u4e00\u573a\u62cd\u89c6\u9891\u5927\u8d5b",
        "\u8c01\u7684\u60c5\u5546\u9ad8 \u60c5\u5546\u5927\u6bd4\u62fc",
        "\u5f53\u6211\u7684\u670b\u53cb\u662f\u660e\u661f",
        "\u5f53\u6211\u7684\u8001\u5e08\u5f88\u6709\u4eba\u81091.0",
        "\u5f53\u6211\u5728\u6f14\u5531\u4f1a\u95e8\u53e3\u9047\u5230\u8001\u5e08",
        "\u5f53\u4f60\u5230\u5927\u56db\uff0c\u4f60\u624d\u4f1a\u660e\u767d\u7684\u4e8b",
        "\u624b\u6413\u7684\u8bba\u6587\u6bd4AI\u5199\u7684AI\u7387\u66f4\u9ad8\uff1f\uff01",
        "\u54ea\u91cc\u53ef\u4ee5\u56de\u6536\u5b9e\u4e60\u751f\u5417",
        "\u5df2\u7ecf\u5230\u4e86\u4e24\u8fb9\u90fd\u80fd\u7406\u89e3\u7684\u5e74\u7eaa",
        "\u5047\u5982\u4ee3\u8bfe\u6210\u7acb\u516c\u53f8",
    ]
    scrape = ScrapeResult(
        platform="xiaohongshu",
        profile_url="https://www.xiaohongshu.com/user/profile/example",
        title="\u53a8\u5b50\u8001\u5e08\u5085\u82f1\u4fca - \u5c0f\u7ea2\u4e66",
        profile_bio="\u539f\u4f20\u5a92\u5927\u5b66\u8001\u5e08 \u5a31\u4e50\u516c\u53f8\u987e\u95ee \u5185\u5bb9\u521b\u4f5c\u8005 \u4ee3\u8868\u4f5c\u54c1\uff1a\u300a\u5927\u5b66\u751f\u751f\u6d3b\u5e38\u8bc6\u8bfe\u300b\u300a\u5927\u5b66\u751f\u6625\u665a\u300b \u5546\u52a1\uff1aMrCookKing 8\u5c81 \u4e2d\u56fd \u6559\u80b2\u535a\u4e3b",
        follower_count="45.2\u4e07",
        recent_post_titles=titles,
    )
    creator = mock_analyze(scrape)

    assert "\u6559\u80b2" in creator.content_categories
    assert "\u5927\u5b66\u751f\u5185\u5bb9" in creator.content_categories
    assert "\u6821\u56ed\u5185\u5bb9" in creator.content_categories
    assert "\u804c\u573a/\u6821\u56ed\u89c2\u5bdf" in creator.content_categories
    assert "\u77ed\u5267\u60c5/\u6bb5\u5b50" in creator.content_categories
    assert "\u6cdb\u5a31\u4e50" in creator.content_categories
    assert "\u5927\u5b66\u751f\u53d7\u4f17" in creator.brand_fit_tags
    assert "\u9002\u5408\u6821\u56ed\u8425\u9500" in creator.brand_fit_tags
    assert "\u9002\u5408\u5185\u5bb9\u521b\u4f5c\u5de5\u5177\u63a8\u5e7f" in creator.brand_fit_tags
    assert creator.risk_flags == []
    assert "\u57fa\u4e8e\u516c\u5f00\u9875\u9762\u5143\u6570\u636e" not in creator.summary
