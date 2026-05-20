# KOLClaw 达人主页分析 MVP

KOLClaw Creator Analysis MVP is a minimal FastAPI demo for creator profile analysis and brand brief matching.

The service scrapes public creator profile pages, detects login/CAPTCHA/access-control pages, returns structured creator analysis, stores successful analyses in SQLite, and matches saved creators against brand briefs. When `LLM_API_KEY` is not configured, it uses deterministic rule-based analysis so the demo can run without an LLM account.

## Main Features

- `POST /analyze-profile` scrapes a creator page and returns creator profile JSON.
- `POST /resume-task/{task_id}` resumes a manual-verification browser task after login or CAPTCHA.
- `POST /match-brief` matches stored creators to a brand brief with rule-based token overlap.
- Access-control detection skips login, CAPTCHA, rate-limit, and empty social-profile pages before analysis.
- SQLite persistence stores creators, platform accounts, content samples, tags, risk records, and matching data.
- Optional OpenAI-compatible LLM analysis through `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL`.

## Folder Structure

```text
.
|-- app/
|   |-- api/
|   |   `-- routes.py              # FastAPI route handlers and task state
|   |-- core/
|   |   |-- access_control.py      # Login/CAPTCHA/block/empty-page detection
|   |   `-- config.py              # Project paths and environment helpers
|   |-- models/
|   |   `-- schemas.py             # Pydantic request/response models
|   |-- services/
|   |   |-- analyzer.py            # LLM call, rule-based analyzer, normalization
|   |   |-- matcher.py             # Brand brief matching
|   |   `-- scraper.py             # Playwright/urllib scraping and platform extraction
|   |-- storage/
|   |   `-- database.py            # SQLite schema and persistence helpers
|   `-- main.py                    # FastAPI app entry point
|-- .env.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```

Ignored local runtime files include `.venv/`, `__pycache__/`, `.pytest_cache/`, `.pytest_tmp/`, `pytest-cache-files-*`, `*.sqlite3`, logs, and `storage_states/`.

## Requirements

- Python 3.11 or 3.12 recommended for Playwright/manual verification on Windows
- Chromium browser runtime for Playwright when scraping JavaScript-heavy pages or using manual verification

Python 3.14 can run the rule-based demo path, but Playwright subprocess launch is intentionally treated as unsupported in this project.

## Installation

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Use the environment template as a reference:

```powershell
Copy-Item .env.example .env
```

The app reads environment variables from the current shell. It does not automatically load `.env`.

Optional LLM configuration:

```powershell
$env:LLM_API_KEY="your_api_key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
```

DeepSeek-compatible example:

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

