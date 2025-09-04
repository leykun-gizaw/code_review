## Project Overview

Automated repository analysis and scoring pipeline consisting of:

- **Analyzer (`analyzer.py`)**: Runs rubric‑driven checks (file existence, git history, AI content checks) and produces Markdown + JSON reports.
- **Final Scorer (`final_scorer.py`)**: Consumes analyzer output (JSON preferred), applies a second scoring rubric, generates per‑criterion scores, a weighted overall score, and an overall review comment.
- **Persistence Layer (`persistence_single.py`)**: Single PostgreSQL table (`analysis_runs`) storing inputs, analyzer/scorer artifacts, AI caches, provenance (commit / branch), and statuses.
- **Async Worker (in `api.py`)**: Clones the target repo, runs analyzer & scorer, updates DB. Triggered explicitly via an enqueue endpoint (decoupled create vs analyze workflow).
- **Flask API (`api.py`)**: Endpoints to create runs, list runs, view a single run, and enqueue analysis jobs. Basic CORS enabled.
- **React + Vite Frontend (`frontend/`)**: Create runs, list existing runs, enqueue analysis, and view formatted analyzer & scorer markdown (with tables via `react-markdown` + `remark-gfm`).
- **AI Integration (Gemini)**: Cached, rate limited calls using the Google Gemini SDK (`from google import genai`).

## Key Features

- Single table persistence for simplicity and easy querying.
- AI call caching (analyzer + scorer) to avoid recomputation and minimize cost.
- Exponential backoff + rate limiting for AI requests.
- Deterministic discrete scoring (0.0 → 1.0, step 0.1) enforcement.
- Weighted overall score with optional summary comment.
- Resumable runs (re‑enqueue only reprocesses missing phases).
- Git provenance capture: branch + commit hash stored with artifacts.
- Robust logging with configurable log file.
- Frontend Markdown rendering (GFM tables) for human‑friendly output.

## Architecture (Textual)

```
Frontend (React) --> Flask API (/runs, /runs/:id, /runs/:id/enqueue)
                                             |
                                  PostgreSQL (analysis_runs)
                                             |
                                 Worker Thread (queue)
                                             |
                                    git clone target repo
                                             |
                          analyzer.py -> analyzer_md/json + cache
                                             |
                      final_scorer.py -> final_scorer_md/json + score + cache
```

## Data Flow

1. User creates a run (email + GitHub URL) → row inserted (status=PENDING).
2. User clicks Analyze (enqueue) → run id placed on queue → worker picks it.
3. Worker clones repository → runs analyzer (if not already done) → persists outputs → status=ANALYZED.
4. Worker runs final scorer (if not already done) → persists outputs + score → status=DONE.
5. Frontend polls run until status transitions to DONE (or ERROR).

## Stack

| Layer          | Tech                                                             |
| -------------- | ---------------------------------------------------------------- |
| Backend API    | Python 3, Flask                                                  |
| Async          | Python `threading` + `queue`                                     |
| DB             | PostgreSQL + `psycopg`                                           |
| AI             | Google Gemini (`google-genai`)                                   |
| Frontend       | React 18, TypeScript, Vite, Tailwind, react-markdown, remark-gfm |
| Container (DB) | Docker / docker compose                                          |

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & docker compose
- Google Gemini API Key

## Quick Start

```bash
git clone <your-fork-url>
cd code_review

python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install flask psycopg[binary] python-dotenv google-genai pyyaml

cp .env .env.local 2>/dev/null || true   # or create .env manually
vi .env   # fill GOOGLE_API_KEY and DB vars

docker compose up -d
python -c "import persistence_single as p; p.init_db()"

python api.py  # API on http://localhost:5000

cd frontend
npm install
npm run dev   # http://localhost:5173
```

In the UI: create run → click Analyze → open run details.

## Detailed Setup

### Environment (`.env` example)

```
GOOGLE_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-2.5-flash
AI_MAX_CALLS_PER_MINUTE=5
POSTGRES_DB=analysis_db
POSTGRES_USER=leykun
POSTGRES_PASSWORD=password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
API_PORT=5000
CORS_ALLOW_ORIGINS=http://localhost:5173
ERROR_LOG_PATH=error.log
LOG_LEVEL=INFO
```

### Initialize Database

```bash
python -c "import persistence_single as p; p.init_db()"
```

### Run Analyzer & Scorer Manually (CLI)

```bash
python analyzer.py        # interactive prompt for repo path
python final_scorer.py analysis_report.json
```

## API Endpoints

| Method | Endpoint           | Body                | Description                       |
| ------ | ------------------ | ------------------- | --------------------------------- |
| POST   | /runs              | {email, github_url} | Create run (status=PENDING)       |
| GET    | /runs?limit=N      | –                   | List runs (desc id)               |
| GET    | /runs/<id>         | –                   | Run details                       |
| POST   | /runs/<id>/enqueue | –                   | Queue analysis (if PENDING/ERROR) |

### Sample Run JSON

```json
{
  "id": 1,
  "email": "user@example.com",
  "github_url": "https://github.com/org/repo.git",
  "status": "DONE",
  "overall_score": 0.72,
  "commit_hash": "abcdef1234",
  "branch_name": "main"
}
```

## Database Schema Summary

`analysis_runs` stores: email, github_url, commit_hash, branch_name, analyzer_md/json, final_scorer_md/json, final_scorer_json, overall_score, analyzer_ai_cache, scorer_ai_cache, tool versions, status, created_at, updated_at, analysis_started_at.

Statuses: PENDING → RUNNING → ANALYZED (analyzer done) → DONE (scorer done) or ERROR.

## Analyzer

- Check types: `file_exists`, `git_commit_count`, `ai_check`.
- AI prompts built with contextual file snippets or git log.
- Caching via `.ai_cache.json` (SHA-256 of prompt) — persisted to DB.

## Final Scorer

- Uses compact `name::status` lines from analyzer JSON.
- Discrete scoring (0.0 .. 1.0 step 0.1) enforced; overrides supported.
- Weighted average + optional summary comment.
- Cache in `.final_score_cache.json` persisted.

## Caching & Rate Limiting

- Analyzer: token bucket + exponential backoff.
- Scorer: minimum interval + exponential backoff.

## Logging

- File + stdout logging; path from `ERROR_LOG_PATH`.
- Worker exceptions store truncated message in DB when ERROR.

## Environment Variable Reference

| Var                             | Purpose                     |
| ------------------------------- | --------------------------- |
| GOOGLE_API_KEY                  | Gemini API key              |
| GEMINI_MODEL                    | Model name                  |
| AI_MAX_CALLS_PER_MINUTE         | Analyzer AI throughput      |
| FINAL_SCORER_MIN_INTERVAL       | Gap between scorer calls    |
| FINAL_SCORER_RETRIES            | Scorer retry attempts       |
| FINAL_SCORER_MAX_ANALYZER_CHARS | Truncation guard            |
| POSTGRES\_\*                    | DB connection pieces        |
| DATABASE_URL                    | Optional DSN override       |
| API_PORT                        | Flask port                  |
| CORS_ALLOW_ORIGINS              | Allowed origins for CORS    |
| ERROR_LOG_PATH                  | Log file path               |
| LOG_LEVEL                       | Logging level               |
| FINAL_SCORER_SUMMARY            | 1/0 include overall comment |

## Troubleshooting

| Issue                | Cause              | Fix                                |
| -------------------- | ------------------ | ---------------------------------- |
| CORS blocked         | Origin not allowed | Set `CORS_ALLOW_ORIGINS` correctly |
| AI failures          | Missing / bad key  | Update `GOOGLE_API_KEY`            |
| Stuck RUNNING        | Worker exception   | Check `error.log`, re-enqueue      |
| Tables not rendering | Missing remark-gfm | Ensure dependency installed        |
| Repeated AI cost     | Cache file wiped   | Preserve `.ai_cache.json`          |

### Inspect Recent Runs

```bash
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT id,email,status,overall_score FROM analysis_runs ORDER BY id DESC LIMIT 10;"
```

### Force Re-run

```sql
UPDATE analysis_runs SET analyzer_md=NULL, analyzer_json=NULL, final_scorer_md=NULL, final_scorer_json=NULL, overall_score=NULL, status='PENDING' WHERE id=<ID>;
```

## Roadmap Ideas

- Authentication & user scoping
- Websocket progress updates
- Advanced pagination / filtering endpoints
- Pluggable rubrics per project type
- Alternative AI provider abstraction

## License

Add a LICENSE file (MIT / Apache-2.0 / etc.).

---

**Happy analyzing!**
