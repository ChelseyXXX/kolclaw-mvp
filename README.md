# KOLClaw Creator Analysis MVP

KOLClaw Creator Analysis MVP is a small FastAPI service for creator profile analysis and brand brief matching.

It supports:

- `POST /analyze-profile`: scrape a creator homepage, detect login/CAPTCHA/access-control pages, and return structured creator analysis.
- `POST /resume-task/{task_id}`: resume a manual verification task after login or CAPTCHA is completed in a headed browser.
- `POST /match-brief`: match saved creator records against a brand brief using rule-based token overlap.
- SQLite persistence for creator profiles, platform accounts, content samples, tags, risks, and matching data.

The default analyzer is deterministic rule-based logic when `LLM_API_KEY` is not configured. If an OpenAI-compatible API key is configured, the app calls the configured LLM endpoint through `httpx`.

## Project Structure

```text
.
├── app/                         # Core FastAPI app and business logic
│   ├── main.py                  # API routes and manual verification workflow
│   ├── scraper.py               # Playwright/urllib scraping and platform extraction
│   ├── access_control.py        # Login/CAPTCHA/block/empty-page detection
│   ├── llm.py                   # LLM call, rule-based analyzer, normalization
│   ├── db.py                    # SQLite schema and persistence helpers
│   ├── matcher.py               # Brand brief matching
│   └── schemas.py               # Pydantic request/response models
├── docs/
│   └── solution_zh.md           # Original Chinese solution notes
├── prompts/
│   └── profile_analysis_prompt.md
├── tests/
│   ├── fixtures/
│   │   └── creator_analysis_response.json
│   └── test_core.py             # Current regression tests
├── .env.example                 # Environment variable template
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

Ignored local runtime files include `.venv/`, `__pycache__/`, `.pytest_cache/`, `.pytest_tmp/`, `pytest-cache-files-*`, `*.sqlite3`, logs, and `storage_states/`.

## Requirements

- Python 3.11 or 3.12 recommended
- Chromium browser runtime for Playwright when using JavaScript-heavy pages or manual verification

On Windows, run Uvicorn without `--reload` when using Playwright/manual verification. Python 3.14 and Windows selector event loops can prevent Playwright from launching subprocesses; the app falls back to `urllib` for non-manual scraping when possible.

## Setup

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Use the template as a reference for local environment variables:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`.
The app reads environment variables from the current shell. It does not automatically load `.env`.

Optional LLM variables:

```powershell
$env:LLM_API_KEY="your_api_key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
```

For DeepSeek-compatible usage, set:

```powershell
$env:LLM_BASE_URL="https://api.deepseek.com"
$env:LLM_MODEL="deepseek-chat"
```

## Run

```powershell
python -m uvicorn app.main:app
```

Open the API docs:

```text
http://127.0.0.1:8000/docs
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Analyze a profile:

```powershell
curl -X POST http://127.0.0.1:8000/analyze-profile `
  -H "Content-Type: application/json" `
  -d "{\"profile_url\":\"https://example.com\",\"brand_brief\":\"young women's light sportswear brand\"}"
```

Match a brief:

```powershell
curl -X POST http://127.0.0.1:8000/match-brief `
  -H "Content-Type: application/json" `
  -d "{\"brand_brief\":\"lifestyle and light sports creator, low risk\",\"limit\":5}"
```

## Tests

The test suite is offline and does not require network access or Playwright browser launch.

```powershell
python -m pytest
```

Current tests cover:

- Pydantic request/response shape
- Required creator JSON schema fixture
- Platform detection
- Login/CAPTCHA/access-control detection
- Xiaohongshu profile parsing and noise filtering
- Rule-based analysis fallbacks
- SQLite save and brief matching
- Manual verification failure response shape

## Notes For GitHub

Before committing, check:

```powershell
git status --ignored --short
```

Do not commit local runtime artifacts:

- `.venv/`
- `.env`
- `kolclaw_demo.sqlite3`
- `storage_states/`
- `__pycache__/`
- `.pytest_cache/`
- `.pytest_tmp/`
- `pytest-cache-files-*`
- logs
