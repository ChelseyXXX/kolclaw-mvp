# KOLClaw Creator Analysis MVP

Minimal demo for the KOLClaw AI intern test, covering:

- Task 1: creator homepage analysis MVP
- Task 2: dynamic creator knowledge base design
- Bonus: LLM routing and cost optimization

The main explanation document is in Chinese:

- `docs/solution_zh.md`

Sample default output:

- `examples/sample_output.json`

## Tech Stack

- Python 3.11 or 3.12 recommended
- FastAPI
- Playwright
- SQLite
- Optional OpenAI-compatible LLM API

The code, README, API fields, and JSON keys use English. The LLM prompt asks the model to return Chinese values with English JSON keys.

## Setup

Use Python 3.11 or 3.12 on Windows. Python 3.14 may fail when Playwright launches its subprocess transport.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Optional LLM environment variables:

PowerShell:

```powershell
$env:LLM_API_KEY="your_api_key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
```

Git Bash:

```bash
export LLM_API_KEY="your_api_key"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-chat"
```

For DeepSeek, set `LLM_BASE_URL` to `https://api.deepseek.com`. Do not include `/chat/completions`. The app also normalizes this if it is accidentally included.

If `LLM_API_KEY` is not set, the app uses a deterministic mock analyzer so the demo can still run.

If Playwright is not installed or Playwright launch fails in non-manual mode, the scraper falls back to a standard-library HTTP/HTML extractor for simple public pages. Playwright is still required for JavaScript-heavy pages and manual verification mode.

On Windows Python 3.14, non-manual scraping skips Playwright and uses the HTTP/HTML fallback automatically to avoid the `asyncio.create_subprocess_exec` subprocess issue.

For Xiaohongshu pages, the scraper applies lightweight profile-section parsing before the LLM/mock analyzer runs. It prefers visible profile bio and stats over `meta_description`, filters legal/footer/navigation noise, and only keeps conservative note-like URLs.

## Known Issue: Windows + Python 3.14 + Playwright

On Windows, Python 3.14 may raise:

```text
NotImplementedError at asyncio.create_subprocess_exec
```

This happens when Playwright cannot launch its subprocess transport with the active asyncio event loop. The app now sets a Windows-compatible `asyncio.WindowsProactorEventLoopPolicy` before Playwright is used, but Python 3.11 or 3.12 is still recommended for this demo.

## Run API

```bash
uvicorn app.main:app --reload
```

Open:

- `http://127.0.0.1:8000/docs`

## Analyze a Profile

```bash
curl -X POST http://127.0.0.1:8000/analyze-profile ^
  -H "Content-Type: application/json" ^
  -d "{\"profile_url\":\"https://example.com\",\"brand_brief\":\"young women's light sportswear brand\"}"
```

Default successful response:

```json
{
  "platform": "website",
  "profile_url": "https://example.com",
  "nickname": "Example Domain",
  "bio": "Chinese profile bio returned by the LLM or mock analyzer",
  "follower_count": "unknown",
  "content_categories": ["Chinese category"],
  "recent_post_titles": [],
  "recent_post_links": [],
  "brand_fit_tags": ["Chinese brand-fit tag"],
  "risk_flags": [],
  "summary": "Chinese creator summary"
}
```

This default response intentionally matches the original task requirement exactly. It does not include `status`, `creator`, `raw_extraction`, `message`, or `manual_verification_required`.

For debugging, pass `debug=true`:

```bash
curl -X POST http://127.0.0.1:8000/analyze-profile ^
  -H "Content-Type: application/json" ^
  -d "{\"profile_url\":\"https://example.com\",\"debug\":true}"
```

Debug response shape:

```json
{
  "status": "completed",
  "manual_verification_required": false,
  "analysis_source": "llm",
  "llm_provider": "deepseek",
  "llm_model": "deepseek-chat",
  "api_key_detected": true,
  "creator": {
    "platform": "website",
    "profile_url": "https://example.com",
    "nickname": "Example Domain",
    "bio": "Chinese profile bio returned by the LLM or mock analyzer",
    "follower_count": "unknown",
    "content_categories": ["Chinese category"],
    "recent_post_titles": [],
    "recent_post_links": [],
    "brand_fit_tags": ["Chinese brand-fit tag"],
    "risk_flags": [],
    "summary": "Chinese creator summary"
  },
  "raw_extraction": {},
  "message": null
}
```

If manual verification is required, the API returns a status response:

```json
{
  "status": "manual_verification_required",
  "manual_verification_required": true,
  "message": "Login or CAPTCHA-like content was detected. Retry with `manual_verification=true` to pause in a headed browser.",
  "resume_token": "example-token"
}
```

## Match a Brief

```bash
curl -X POST http://127.0.0.1:8000/match-brief ^
  -H "Content-Type: application/json" ^
  -d "{\"brand_brief\":\"lifestyle and light sports creator, low risk\",\"limit\":5}"
```

## Manual Verification Flow

For pages that require login or CAPTCHA:

1. Request analysis with `manual_verification=true`.
2. Playwright launches a headed Chromium browser.
3. The scraper detects login/CAPTCHA keywords and pauses for manual verification.
4. Complete login or CAPTCHA in the browser.
5. Press Enter in the API server terminal to resume extraction.

This is intentionally simple for a 1-2 day MVP. A production version should store browser sessions, persist cookies, and expose an operator queue.

## Tests

The tests focus on schema normalization, SQLite persistence, and brief matching. They do not require network access or Playwright.

```bash
python -m pytest
```
