# QueueStorm Investigator — Frontend

A static, zero-build UI for the QueueStorm Investigator API.
Open `index.html` in a browser, fill the form (or load a sample case), and see the structured investigation verdict.

## Files

- `index.html` — markup
- `styles.css` — dark theme, responsive grid
- `app.js`   — vanilla JS; no framework, no build step

## Running locally

The frontend must be served over HTTP (browsers block `fetch()` to local files via `file://` for cross-origin JSON). Two options:

### Option A — use the project's static file server (recommended)

A Python one-liner in the project root serves both the API and the frontend on the same origin, so CORS is not needed:

```powershell
cd "d:\Complaint Investigator"
python -m http.server 8000 --directory frontend
```

Then open <http://localhost:8000> in your browser.

### Option B — separate API and frontend ports

Start the API:

```powershell
cd "d:\Complaint Investigator"
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then serve the frontend on a different port:

```powershell
cd "d:\Complaint Investigator\frontend"
python -m http.server 5500
```

Open <http://localhost:5500>. The frontend's API base is `http://localhost:8000` by default — override at runtime with `?api=http://host:port` in the URL.

## Configuring the API port

The frontend reads the backend port in this order:

1. URL query param `?api_port=NNNN` (highest priority — handy for demos)
2. Build-time placeholder `__API_PORT__` in `index.html`, replaced by `FRONTEND_API_PORT` at deploy time
3. Default `8000` (matches `BACKEND_PORT` default in `backend/.env.example`)

For local dev with non-default ports, the cleanest path is:

```powershell
# Tell the backend to listen on 9000
$env:BACKEND_PORT=9000; uicorn main:app --host 0.0.0.0 --port 9000

# Tell the frontend where to find it (no rebuild needed)
start http://localhost:5500/?api_port=9000
```

For deploy-time replacement, run a one-line sed on `frontend/index.html` to swap `__API_PORT__` for the real port (or set it as a static-site build env var on Render/Netlify).

## Features

- All request fields from `models.py`: `ticket_id`, `complaint`, `language`, `channel`, `user_type`, `campaign_context`, `transaction_history` (repeatable rows with full enum dropdowns), `metadata` (key/value).
- "Load sample case" dropdown pre-fills the form from `SUST_Preli_Sample_Cases.json` (served from the project root).
- Verdict panel shows every required field: severity (color-coded), evidence_verdict, department, case_type, relevant_transaction_id, confidence, agent_summary, recommended_next_action, customer_reply, human_review_required, reason_codes.
- Health pill in the top-right reflects `GET /health` status.
- Error responses (400/422/500) are rendered inline with the raw body for debugging.
- Latency reported in milliseconds per request.

## Notes

- The frontend does **not** store or log API keys; the Gemini key stays server-side in `.env`.
- No npm, no bundler. Open the files and edit them directly.
