# Contract Frontend (Vite + React)

Minimal, production-ready UI for streaming contract generation over SSE.

## Quickstart
```bash
npm i
npm run dev
# ensure backend is running at the URL in .env.local
```

Set backend URL in `.env.local`:
```
VITE_BACKEND_URL=http://localhost:8000
```

## Expected Backend Endpoints
- `POST /generate` → `{ jobId }`
- `GET /stream/:jobId` (SSE) emits events:
  - `event: chunk` with `data` = HTML fragment
  - `event: error` (optional)
  - `event: done` when finished
- `POST /stop` → `{ ok: true }`

## Customize
- Split components further under `src/components/`.
- Plug in DOMPurify in `src/lib/sanitize.js` if you need sanitization.
- Styling is inline for brevity; move into CSS modules or Tailwind if preferred.
