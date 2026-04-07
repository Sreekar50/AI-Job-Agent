# AI Job Application Agent

An end-to-end agentic pipeline that autonomously applies to jobs — tailoring resumes, generating cover letters, detecting ATS platforms, filling forms intelligently, and submitting applications.

---

## Architecture Overview

```
ai_job_agent/
├── backend/
│   ├── api/              # FastAPI routes (candidates, jobs, websocket)
│   ├── agents/           # LangGraph agent pipeline (5 nodes)
│   ├── db/               # SQLAlchemy models + Alembic migrations
│   ├── services/         # ATS detector, browser service, LLM service, resume service
│   └── utils/            # Config, HITL manager, logging
├── demo/                 # Seed data, tailored resume PDFs
├── scripts/              # DB init, seed runner, add_custom_answer, demo_hitl
├── tests/                # Unit + integration tests
├── .env.example
├── docker-compose.yml
├── requirements.txt
└── main.py
```

---

## How to Run the Demo

### Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Playwright browsers (`playwright install chromium`)

### 1. Clone and configure

```bash
git clone https://github.com/Sreekar50/AI-Job-Agent
cd AI_Job_Agent
cp .env.example .env 
# Fill in your API keys in .env (according to the .env template in git)
```

### 2. Start PostgreSQL

```bash
docker-compose up -d db
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Initialize DB + seed demo user

```bash
python scripts/init_db.py
python scripts/seed_demo.py
# Note the candidate ID printed at the end
```

### 5. Run the agent

```bash
# Optional: start FastAPI server for HITL WebSocket + REST API
uvicorn main:app --reload

# Run the job queue for the demo candidate
python scripts/run_agent.py
```

The agent will process 6 queued jobs across Greenhouse, Lever, Workday, LinkedIn, and iCIMS automatically.

---

## Starting Fresh (Reset the Database)

To drop all tables and start from a clean state before a new run, connect to your PostgreSQL instance and execute:

```sql
DO $$ DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public')
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END $$;
```

Then re-initialise and re-seed:

```bash
python scripts/init_db.py
python scripts/seed_demo.py
```

> **Note:** This drops every table in the `public` schema including all candidates, jobs, and custom answers. Only run this when you want a fully clean slate.

---

## Candidate DB Structure

### Tables

**candidates** — core profile

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| full_name | str | |
| email | str | Unique |
| phone | str | |
| location | str | |
| linkedin_url | str | |
| github_url | str | |
| resume_path | str | Path to base resume PDF |
| summary | text | Professional summary |
| years_of_experience | int | |

**work_experiences** — job history (FK → candidates)

**educations** — degrees (FK → candidates)

**skills** — skill tags with proficiency levels (FK → candidates)

**custom_answers** — key-value store for form questions not on any resume

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | |
| candidate_id | UUID | FK |
| question_key | str | e.g. `sponsorship_required` |
| answer | str | e.g. `No` |
| description | text | Human-readable hint |

> **Extending:** Add a new entry at any time — picked up on the next run automatically, no code changes needed.

**jobs** — application queue

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | |
| url | str | Job posting URL |
| company / title | str | Extracted from job page |
| ats_platform | enum | workday / greenhouse / lever / linkedin / icims / unknown |
| status | enum | queued / in_progress / applied / failed / backlog |
| failure_reason | text | Populated if status = failed |
| unanswered_fields | JSON | Fields agent couldn't answer |
| tailored_resume_path | str | Path to the generated PDF |
| cover_letter | text | Generated cover letter text |
| created_at / started_at / applied_at | datetime | |

### Extending the candidate DB

```bash
# Add a custom answer (no code change needed):
python scripts/add_custom_answer.py --key "notice_period" --value "30 days"

# Or via API:
POST /api/candidates/{id}/custom-answers
{"question_key": "notice_period", "answer": "30 days"}

# Add a new job to the queue:
POST /api/jobs
{"url": "https://jobs.lever.co/company/job-id", "candidate_id": "..."}
```

---

## ATS Detection

Detection uses a two-step approach — no hardcoded per-URL logic:

1. **URL pattern matching** — regex rules per known ATS (`myworkdayjobs.com`, `greenhouse.io`, `lever.co`, `linkedin.com/jobs`, `icims.com`). Fast, requires no browser.
2. **DOM fingerprinting** — if the URL is ambiguous, loads the page and inspects the rendered DOM for ATS-specific signatures (unique element IDs, class names, `data-*` attributes, page source strings).

**Supported platforms:** Workday, Greenhouse, Lever, LinkedIn, iCIMS (+ generic fallback for unknown ATS).

Detection generalises to new job URLs automatically — adding a new employer doesn't require a new rule, only a new URL pattern if it's a new ATS platform.

---

## Form Field Mapping

The agent resolves every form field through a 5-step precedence chain:

1. **Profile DB** — direct lookup of name, email, phone, location, LinkedIn URL, GitHub URL, years of experience, and professional summary via regex-matched field labels.
2. **Custom Answers** — key-value store checked by exact key match, then fuzzy word-overlap match. Covers sponsorship status, salary expectation, notice period, relocation preference, demographics, etc.
3. **LLM Inference** — if neither DB nor custom answers resolve the field, the LLM (Groq `llama-3.3-70b-versatile`) is prompted with the full candidate profile + job description to infer a reasonable answer. Returns a confidence score (0–1).
4. **HITL Escalation** — if LLM confidence < 0.6 or `should_escalate=true`, the agent pauses and sends the field + LLM suggestion to the user via WebSocket with a 30-second countdown.
5. **Log & Skip** — if still unanswered (LLM had no basis and HITL timed out), the field is logged to `jobs.unanswered_fields` for the user to review and add to custom answers before the next run.

---

## HITL (Human-in-the-Loop)

- Triggers **only** when the agent encounters a form field it cannot answer with confidence (ambiguous, sensitive, or outside the DB + LLM scope).
- Sends a WebSocket notification to all connected clients with the field label, type, available options, and a 30-second countdown.
- **User responds in time** → answer is used to fill the field, saved to `custom_answers` for future runs, agent continues.
- **Timeout / no response** → job is moved to `backlog` status, agent continues to the **next job immediately** (no blocking).
- Submission is **fully automatic** — once all fields are filled the agent submits with no manual trigger.

**Backlog** jobs can be retried after adding the missing answer to `custom_answers`:
```bash
python scripts/add_custom_answer.py --key "sponsorship_required" --value "No"
python scripts/run_agent.py  # retries backlog jobs
```

### Demoing HITL

`scripts/demo_hitl.py` simulates both HITL paths without needing a live browser session:

```bash
# Path 1: agent hits an ambiguous field, user responds within 5s → resolved
python scripts/demo_hitl.py

# Path 2: agent hits an ambiguous field, no response → job moves to backlog after 30s
python scripts/demo_hitl.py timeout
```

**How it works:** `demo_hitl.py` schedules a concurrent `_auto_submit()` coroutine alongside `request_answer()`. In the `respond` path, it calls `hitl_manager.submit_answer()` after 5 seconds, resolving the Future well before the 30-second timeout. In the `timeout` path, no submission is scheduled — the countdown runs to zero and the job is moved to backlog automatically.

---

## Scaling

| Concern | Approach |
|---------|----------|
| Multiple users | Each candidate has isolated DB rows; `run_queue()` accepts `candidate_id` param |
| Concurrent agents | Use Redis + Celery (or ARQ) as job queue; each worker runs one independent LangGraph pipeline |
| Browser isolation | Browserless.io for cloud browsers; or per-worker Playwright contexts with `--no-sandbox` |
| Queue infrastructure | Replace in-memory loop with Redis Streams or AWS SQS for durable, distributed job queues |
| Observability | LangSmith tracing for agent steps; structured logs per `job_id` in `agent_logs` table |
| Rate limits | Per-ATS retry logic with exponential backoff + jitter; `MAX_CONCURRENT_JOBS` env var |
| Credential security | All secrets via `.env` only — never committed to source control |