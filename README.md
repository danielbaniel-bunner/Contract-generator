AI Contract Generator — Monorepo (Frontend + Backend)

LLM-powered contract generator with a deterministic, RAG-free pipeline.
Backend streams post-QC HTML to the browser via Server-Sent Events (SSE); the frontend renders it live.
Stage-2 “Guidance Notes” propagate to every later stage, and Stage-5 drafts the first main section up front to anchor the rest.

Contents

Features

Repo Structure

Quick Start

Option A — Docker Compose (recommended)

Option B — Local Dev (no Docker)

Configuration & Env Vars

Architecture

Data Flow

Pipeline Stages

API

Deployment

Nginx Reverse Proxy (SSE-safe)

Troubleshooting

Design Trade-offs

Operational Notes

Security & Privacy

License

Features

Deterministic 6-stage pipeline (no retrieval): infer → guidance → outline → first part → sections → QC/fix.

Guidance Notes everywhere: Stage-2 notes feed Stages 3–6 (outline, first part, sections, QC).

Anchor-first drafting: Stage-5 drafts the first main section first and uses it as authoritative context for the rest (parallel).

Clean streaming: only final, post-QC HTML is sent as "chunk" SSE events.

Minimal sanitization on the HTML before streaming.

Configurable concurrency, token sizes, chunk sizes.

Repo Structure
.
├─ backend/
│  ├─ app.py                      # FastAPI app: /generate, /stream/:jobId
│  ├─ contract_pipeline_v3.py     # Orchestrator + stages (notes propagation + anchor-first Stage 5)
│  ├─ config.py                   # Tunables: chunk size, parallelism, TTL, etc.
│  ├─ logging_utils.py            # jlog(...) helper for structured logs
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ App.jsx
│  │  ├─ components/
│  │  │  ├─ Preview.jsx
│  │  │  ├─ PromptForm.jsx
│  │  │  ├─ Toolbar.jsx
│  │  │  └─ StatusBar.jsx
│  │  ├─ hooks/useEventSource.js  # Listens to 'chunk' and 'done'
│  │  └─ lib/{api.js, download.js}
│  ├─ index.html
│  ├─ package.json
│  └─ .env.example
├─ docker-compose.yml
└─ README.md

Quick Start
Option A — Docker Compose (recommended)

Create env files

backend/.env

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# Optional: override config.py via env if supported in your build


frontend/.env

VITE_BACKEND_URL=http://localhost:8000


Build & run

docker compose up --build


Open http://localhost:5173

Option B — Local Dev (no Docker)

Backend

cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # add OPENAI_API_KEY, OPENAI_MODEL
uvicorn app:app --host 0.0.0.0 --port 8000 --reload


Frontend

cd frontend
npm i
cp .env.example .env                # set VITE_BACKEND_URL=http://localhost:8000
npm run dev


Open http://localhost:5173.

Configuration & Env Vars

Backend (backend/.env)

OPENAI_API_KEY — required

OPENAI_MODEL — required (e.g., gpt-4o-mini, gpt-4.1, etc.)

Backend tunables (backend/config.py)

OUTLINE_MIN_SECTIONS — minimum sections for Stage-3 outline

SECTION_TARGET_WORDS — typical target length per section

MAX_PARALLEL_SECTIONS — Stage-5 parallelism after anchor

JOB_TTL_SECONDS — time to keep finished jobs in memory

STREAM_CHARS_PER_EVENT — SSE chunk size for "chunk" events

STREAM_DELAY_MS — artificial delay between chunks (0 = disabled)

You can keep these in config.py. If you export them via env in your own build, ensure config.py reads from os.environ.

Frontend (frontend/.env)

VITE_BACKEND_URL — e.g., http://localhost:8000

Architecture
Data Flow
Browser (EventSource)     Frontend (React)
       │                        │
       │  POST /generate        │  create job → { jobId }
       ├────────────────────────►
       │                        │
       │  GET /stream/:jobId    │  subscribe via EventSource
       ◄────────────────────────┤
       │                        │  handle 'chunk' (HTML), 'done'


Backend (FastAPI/Uvicorn)

POST /generate → creates a Job with the user prompt; returns jobId.

GET /stream/:jobId → SSE stream; emits:

start, variables, outline, progress (status markers),

chunk (final, post-QC HTML),

error, done.

Pipeline Stages

Infer minimal variables (type, jurisdiction, parties).

Guidance + Notes (PRIVATE; uses model’s internal knowledge).
Returns <section>Guidelines</section> and short notes.

Outline (10–16 sections) using Guidance Notes.

First Part (front-matter + global definitions).
Its context folds in Guidance Notes.

Sections (anchor-first + parallel):
Draft first main section sequentially (not “Definitions”),
then draft remaining sections in parallel using:

Stage-2 notes,

Stage-4 context,

Anchor section HTML (authoritative, “do not duplicate”).

QC + Fix (single pass), enforcing Guidance Notes and consistency.
Only then stream HTML as "chunk" events.

API
POST /generate

Request

{ "prompt": "Describe the business context and contract goals..." }


Response

{ "jobId": "186a842963e046c1919cdd71d2bd117c" }

GET /stream/:jobId (SSE)

Headers: Content-Type: text/event-stream, Cache-Control: no-store, Connection: keep-alive, X-Accel-Buffering: no

Events

start — {"job_id":"..."}

variables — inferred variables (JSON)

outline — outline structure (JSON)

progress — text markers: guidelines_ready, first_part_ready, sections_done

chunk — HTML string (final, post-QC)

error — text

done — end of stream (no payload)

Example

# 1) Create a job
curl -s -X POST http://localhost:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"NDA for a UK pilot between Provider and Customer"}'
# → {"jobId":"<id>"}

# 2) Stream it
curl -N http://localhost:8000/stream/<id>
# event: chunk
# data: <section id='front-matter'>...
# ...
# event: done

Deployment
Docker Compose
# Build and start
docker compose up -d --build

# Tail logs
docker compose logs -f backend
docker compose logs -f frontend

Nginx Reverse Proxy (SSE-safe)

If you proxy /stream/, disable buffering:

server {
  listen 80;
  server_name your.domain;

  location / {
    proxy_pass http://frontend:5173;
  }

  location /api/ {
    proxy_pass http://backend:8000/;
  }

  # Critical: SSE path must not be buffered
  location /stream/ {
    proxy_pass http://backend:8000/stream/;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600;
    proxy_send_timeout 3600;

    add_header X-Accel-Buffering no;
  }
}


If frontend and backend are on different origins, enable CORS (either in FastAPI or here).

Troubleshooting

You see SSE events in DevTools > Network but preview doesn’t update
Ensure the frontend listens for 'chunk' (not 'message'). Append e.data to the HTML string and re-render.

All HTML appears at once (no streaming)
A proxy is buffering. Turn buffering off for the SSE route (see Nginx config) and ensure backend sends X-Accel-Buffering: no.

CORS errors
Set VITE_BACKEND_URL properly; enable CORS on the backend if origins differ.

Token/context limits
Reduce MAX_PARALLEL_SECTIONS, lower section target words, or choose a larger-context model.

Intermittent disconnects
SSE is long-lived; keep proxy_read_timeout high and avoid idle timeouts on LB/proxy.

Design Trade-offs

Final-only streaming

Pros: users only see post-QC, stable content; simpler UI.

Cons: first paint comes later than progressive streaming.

Anchor-first drafting

Pros: consistent terminology/allocations across sections; fewer QC edits.

Cons: slight latency before fan-out to parallel drafting.

RAG-free

Pros: predictable, no network dependencies, fast.

Cons: no statutory citations; add a RAG stage later if you need them.

Parallelism

Pros: throughput on long contracts.

Cons: transient token use; bound it via MAX_PARALLEL_SECTIONS.

Operational Notes

Logging: logging_utils.jlog(event, **kv) emits structured logs (e.g., route.stream.open, stage5.anchor.select, stage2.notes_present).

Job lifecycle: Jobs live in memory and are pruned by JOB_TTL_SECONDS.
Clients should: POST /generate → immediately GET /stream/:jobId.

Security & Privacy

No external retrieval. Stage-2 guidance relies on the model’s internal knowledge.

Outputs are not persisted beyond the in-memory job queue.

Add your own logging redaction and retention policies as needed.

License

Private/internal. All rights reserved.
