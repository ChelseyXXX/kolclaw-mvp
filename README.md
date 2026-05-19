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

Use Python 3.11 or 3.12 on Windows. Python 3.14 may fail when Playwright launches its subprocess transport. If you use Playwright on Windows, run Uvicorn without `--reload`.

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

On Windows Python 3.14, or when Uvicorn `--reload` selects a Windows Selector event loop, non-manual scraping skips Playwright and uses the HTTP/HTML fallback automatically to avoid the `asyncio.create_subprocess_exec` subprocess issue.

Manual verification mode still requires a headed Playwright browser. If `manual_verification=true` is used on an incompatible Windows/Python runtime and Playwright cannot launch, the API returns:

```json
{
  "status": "manual_verification_unavailable",
  "manual_verification_required": true,
  "platform": "weibo",
  "message": "Manual verification requires Playwright headed browser, but the browser could not be launched in the current Python/Windows environment. On Windows, run uvicorn without `--reload` when using Playwright, use Python 3.11/3.12, or run without manual_verification.",
  "resume_token": null
}
```

In that case, use Python 3.11 or 3.12, run Uvicorn without `--reload`, install Chromium with `python -m playwright install chromium`, or retry without `manual_verification` to use the HTTP fallback when possible. The app does not send this failed manual-verification page to the LLM and does not return a fake creator profile.

For Xiaohongshu pages, the scraper applies lightweight profile-section parsing before the LLM/mock analyzer runs. It prefers visible profile bio and stats over `meta_description`, filters legal/footer/navigation noise, and only keeps conservative note-like URLs.

## Known Issue: Windows + Uvicorn Reload + Playwright

On Windows, Uvicorn `--reload` and Python 3.14 may raise:

```text
NotImplementedError at asyncio.create_subprocess_exec
```

This happens when Playwright cannot launch its subprocess transport with the active asyncio event loop. Uvicorn's Windows reload subprocess mode can select a Selector event loop, which does not support `asyncio.create_subprocess_exec`. The app detects this and falls back for non-manual scraping, but manual verification still needs a headed Playwright browser.

Install the browser runtime before using Playwright:

```bash
python -m playwright install chromium
```

For Playwright/manual verification on Windows, start the API without reload:

```bash
python -m uvicorn app.main:app
```

## Run API

```bash
python -m uvicorn app.main:app
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

## General Login / CAPTCHA / Access-Control Handling

Many creator platforms may require login, show visitor systems, trigger CAPTCHA, rate-limit traffic, or return an empty shell page. The app now detects platform and access status before sending anything to the LLM.

Supported platform detection includes Xiaohongshu, Weibo, Douyin, Bilibili, TikTok, Instagram, YouTube, and generic websites.

Access-control statuses:

- `normal_accessible`
- `login_required`
- `manual_verification_required`
- `captcha_required`
- `blocked_or_rate_limited`
- `empty_or_invalid_profile`

Blocked/login/CAPTCHA/empty pages are not sent to the LLM. Instead, the API returns a workflow response:

```json
{
  "status": "login_required",
  "manual_verification_required": true,
  "platform": "weibo",
  "message": "Login or verification is required. Please complete it in the opened browser, then call /resume-task/task_xxx.",
  "resume_token": "task_xxx"
}
```

Manual verification flow:

1. Call `POST /analyze-profile` with `manual_verification=true`.
2. The backend launches a visible Playwright Chromium browser.
3. If login/CAPTCHA/blocking is detected, the backend keeps the browser open and stores an in-memory paused task.
4. Complete login or verification in the browser.
5. Call `POST /resume-task/{task_id}` using the returned `resume_token`.
6. The backend reuses the browser context/page, re-scrapes the profile, and continues analysis if the page is accessible.

Xiaohongshu can be used as a success-path demo. Weibo or Douyin pages are useful manual-verification demo cases because they often show visitor/login systems.

With `debug=true`, access-control metadata is included:

```json
{
  "status": "login_required",
  "access_control": {
    "platform": "weibo",
    "access_status": "login_required",
    "detection_reasons": ["Login or platform access-control keywords detected"],
    "matched_keywords": ["Sina Visitor System"],
    "should_skip_llm": true
  },
  "analysis_source": "skipped_due_to_access_control"
}
```

This is intentionally simple for a 1-2 day MVP. Paused tasks are stored in memory, with optional storage state files written under `storage_states/`.

## Tests

The tests focus on schema normalization, SQLite persistence, and brief matching. They do not require network access or Playwright.

```bash
python -m pytest
```
