# QueueStorm Investigator — Setup Guide

A complete, copy-pasteable walkthrough for getting the project running locally on **Windows / PowerShell**. macOS / Linux notes are appended where commands differ.

> Looking for the high-level tour? See [`README.md`](README.md). This document is the **end-to-end recipe** — every command, every gotcha, every "why is this not working" answer.

---

## 1. Prerequisites

| Requirement | Minimum | Recommended | How to verify |
|---|---|---|---|
| Python | 3.10 | 3.11+ (project tested on 3.13) | `python --version` |
| pip | bundled | latest | `python -m pip --version` |
| Git | any | latest | `git --version` |
| Browser | any modern | Chrome / Edge | — |
| Google AI Studio API key | required | — | https://aistudio.google.com/ → *Get API key* (free tier, no billing) |

> **No Node.js, no npm, no Docker, no database.** The whole project is one FastAPI process + a static HTML page.

---

## 2. Clone the repository

```powershell
# PowerShell (Windows)
cd D:\
git clone https://github.com/mdmrafi/QueueStorm-Investigator.git
cd QueueStorm-Investigator
```

```bash
# macOS / Linux
git clone https://github.com/mdmrafi/QueueStorm-Investigator.git
cd QueueStorm-Investigator
```

The folder layout after cloning:

```
QueueStorm-Investigator/
├── backend/           # FastAPI service
│   ├── main.py        # entrypoint
│   ├── models.py
│   ├── evidence_engine.py
│   ├── fallback.py
│   ├── gemini_client.py
│   ├── response_builder.py
│   ├── safety_validator.py
│   ├── test_cases.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/          # static HTML/CSS/JS UI
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── samples.json
├── .gitignore
├── README.md
└── SETUP.md           # ← you are here
```

---

## 3. Create a virtual environment (recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

> If PowerShell blocks the activation script (`…cannot be loaded because running scripts is disabled…`), run once as admin:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
>
> Then re-run `.\.venv\Scripts\Activate.ps1`.

On macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

---

## 4. Install dependencies

```bash
pip install -r backend/requirements.txt
```

This installs:

```
fastapi           # HTTP framework
uvicorn[standard] # ASGI server
pydantic          # validation
google-generativeai  # Gemini SDK
httpx             # async HTTP (used by test suite)
python-dotenv     # .env loader
```

Verify:

```bash
python -c "import fastapi, uvicorn, pydantic, google.generativeai, httpx; print('deps OK')"
```

---

## 5. Configure environment

### 5.1 Copy the template

```powershell
Copy-Item backend\.env.example backend\.env
```

The template ships with sensible defaults:

```dotenv
# Required — paste your key from https://aistudio.google.com/
GOOGLE_API_KEY=your_google_ai_studio_api_key_here

# Optional — pin a specific Gemini model name. Leave commented to let
# gemini_client.py probe-and-pin the first available model.
# GEMINI_MODEL=gemini-2.5-flash

# Optional — change the backend port (default 8000). Match FRONTEND_API_PORT
# (see frontend/index.html build-time replacement) when deploying.
BACKEND_PORT=8000
```

### 5.2 Add your real key

Open `backend/.env` in any editor and replace `your_google_ai_studio_api_key_here` with your actual key. The file is git-ignored — it will never be committed.

> **Never** put the real key in `backend/.env.example`. That file is the public template; it stays a placeholder.

### 5.3 Verify the key is loaded

```bash
python -c "from dotenv import load_dotenv; from pathlib import Path; load_dotenv(Path('backend/.env')); import os; k=os.environ.get('GOOGLE_API_KEY',''); print(f'key loaded, length={len(k)}, starts_with_AIza={k.startswith(\"AIza\")}')"
```

Expected: `key loaded, length=NN, starts_with_AIza=True`. If `length=0`, the file path is wrong — see [§10 Troubleshooting](#10-troubleshooting).

---

## 6. Run the backend

```powershell
# from the project root, with the venv active
python backend\main.py
```

Expected log output:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [PID]
2026-06-26 23:14:22,624 [INFO] queuestorm: QueueStorm backend port configured: 8000
INFO:     Application startup complete.
```

Alternative (if `python backend/main.py` is blocked by reload issues):

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

To run on a different port via env:

```powershell
$env:BACKEND_PORT=9000
python backend\main.py
# or
uvicorn backend.main:app --host 0.0.0.0 --port 9000
```

### 6.1 Verify the backend

In a **second** PowerShell window:

```powershell
curl http://localhost:8000/health
# → {"status":"ok"}
```

If you see `{"status":"ok"}`, the backend is up.

---

## 7. Run the frontend

The frontend is plain static files — no build step. You just need a static HTTP server (browsers block `fetch()` on `file://`).

```powershell
# from the project root
python -m http.server 8001 --directory frontend
```

Open <http://localhost:8001/> in your browser. You should see the QueueStorm Investigator UI with the form on the left and an empty "Investigation verdict" panel on the right.

### 7.1 Tell the frontend where the backend lives

By default the frontend tries `http://<your-hostname>:8000`. Three ways to override:

| Method | When to use |
|---|---|
| **`?api_port=NNNN`** in the URL | Demos / quick tests (e.g. `http://localhost:8001/?api_port=9000`) |
| **`?api=http://host:port`** | Full override for non-localhost backends (e.g. `?api=https://queuestorm.onrender.com`) |
| **Build-time replacement** | Bake `__API_PORT__` in `frontend/index.html` to the real port before deploying |

Example: backend on `9000`:

```powershell
start http://localhost:8001/?api_port=9000
```

### 7.2 Smoke-test in the browser

1. Click the **"Load sample case"** dropdown, pick any case → form auto-fills
2. Click **"Analyze ticket"** → verdict panel fills with a structured JSON-style view (severity, evidence_verdict, department, etc.)
3. Latency is shown in milliseconds; should be < 5 s on a warm model

---

## 8. Run the test suite

```powershell
# backend must be running
python backend\test_cases.py
```

Runs all 10 sample cases plus 6 error-handling checks (missing fields, empty complaint, injection attempt, etc.). Expected:

```
=== TEST 1/10 ===
✓ PASS  ...
...
=== SUMMARY ===
Total: 16   Passed: 16   Failed: 0
```

The script searches for `SUST_Preli_Sample_Cases.json` in three places (script dir, parent dir, CWD) so it works whether you run it from `backend/` or from the project root.

---

## 9. Putting it together — a clean 60-second run

```powershell
# Terminal 1 — backend
cd "D:\Complaint Investigator"
.\.venv\Scripts\Activate.ps1
python backend\main.py

# Terminal 2 — frontend
cd "D:\Complaint Investigator"
python -m http.server 8001 --directory frontend

# Browser
start http://localhost:8001
```

---

## 10. Troubleshooting

### Backend won't start

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | venv not activated or `pip install` skipped | `.\.venv\Scripts\Activate.ps1` then `pip install -r backend/requirements.txt` |
| `ImportError: cannot import name 'X' from 'models'` | Ran `uvicorn main:app` from project root, not `backend.main:app` | Use `uvicorn backend.main:app ...` from project root (the `sys.path.insert` in `main.py` only fires when imported as a package member) |
| `OSError: [WinError 10048] Only one usage of each socket address` | Another process already owns `:8000` | See [§11 Ports](#11-ports--process-management) below |
| `pydantic.ValidationError: … field required` after sending a request | Missing `ticket_id` or empty `complaint` | This is expected — see `400` vs `422` behavior in `main.py` |

### Frontend shows "Network error: Failed to fetch"

- Backend is **not** running on the configured port → start it (see [§6](#6-run-the-backend))
- Wrong port → open DevTools → Network tab, check the URL the request hit. Use `?api_port=NNNN` to override
- CORS issue → the backend allows `*`, so any localhost origin is fine. If you proxy through a different scheme/host, check the response headers

### Gemini never extracts anything (every response looks like the regex fallback)

- Check backend log for `Gemini extraction failed`. Common causes:
  - `GOOGLE_API_KEY` missing or wrong → see [§5.3](#53-verify-the-key-is-loaded)
  - Your Google Cloud project has `limit: 0` on every Gemini model → try setting `GEMINI_MODEL=gemini-2.5-flash` in `backend/.env` explicitly. The probe loop in `gemini_client.py` tries `gemini-2.5-flash` → `gemini-flash-latest` → `gemini-flash-lite-latest` → `gemini-2.0-flash` → `gemini-2.0-flash-lite` in order
  - Network egress blocked → check firewall / proxy
- When the fallback is active, the response is still correct — just less rich. Look for `agent_summary` mentioning specific TXN IDs to confirm real extraction

### "Address already in use" / port already bound (Windows quirk)

Windows **does not** match Linux's `SO_REUSEADDR` semantics. If `python -m http.server 8000` was started earlier in a terminal you closed, the socket can stay in `TIME_WAIT` and a new bind fails silently while TCP still routes to the old owner.

Quick fix:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-NetTCPConnection -LocalPort 8001 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Then restart backend / frontend.

---

## 11. Ports & process management

| Service | Default port | Override | Where to change |
|---|---|---|---|
| Backend (uvicorn) | `8000` | `BACKEND_PORT` env var | `backend/.env` or shell |
| Frontend (http.server) | `8001` | `--port NNNN` flag | `python -m http.server NNNN --directory frontend` |

The frontend reads the backend port in this order:

1. `?api_port=NNNN` URL query (highest priority)
2. `__API_PORT__` build-time placeholder in `frontend/index.html`
3. Default `8000`

**To change both at once for a local demo:**

```powershell
# Terminal 1
$env:BACKEND_PORT=9000; python backend\main.py

# Terminal 2
python -m http.server 8001 --directory frontend

# Browser
start http://localhost:8001/?api_port=9000
```

**Useful one-liners:**

```powershell
# Show all python processes and what ports they own
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{
        PID      = $_.Id
        Started  = $_.StartTime
        Ports    = (Get-NetTCPConnection -OwningProcess $_.Id -State Listen -EA SilentlyContinue).LocalPort -join ','
    }
} | Format-Table -AutoSize

# Kill everything on port 8000 (careful)
Get-NetTCPConnection -LocalPort 8000 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## 12. Environment variables reference

| Variable | Required? | Default | Where read | Purpose |
|---|---|---|---|---|
| `GOOGLE_API_KEY` | **Yes** | — | `backend/gemini_client.py` | Google AI Studio key |
| `GEMINI_MODEL` | No | (auto) | `backend/gemini_client.py` | Pin a specific Gemini model |
| `BACKEND_PORT` | No | `8000` | `backend/main.py` | Port uvicorn binds to |

Everything else (`BACKEND_*`, `HOST`, `LOG_LEVEL`) can be set via standard uvicorn / FastAPI env vars.

---

## 13. Next steps — deploying

This repo is **deploy-ready**. Two common paths:

### Path A — Render (easiest, free tier)

1. Sign in at https://render.com → **New +** → **Web Service** → connect this repo
2. Root directory: `backend`. Build: `pip install -r requirements.txt`. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Add env var `GOOGLE_API_KEY=<your-key>` in the dashboard
4. Wait ~2 min → URL like `https://queuestorm.onrender.com`
5. Repeat for the frontend as a **Static Site** with root `frontend/`
6. To lock the frontend to the deployed backend URL, bake it in at deploy time:

   ```powershell
   (Get-Content frontend\index.html) -replace '__API_PORT__','8000' | Set-Content frontend\index.html
   ```

### Path B — single VPS (full control, ~$5/mo)

```bash
# on the VPS (Ubuntu 24.04)
git clone https://github.com/mdmrafi/QueueStorm-Investigator.git
cd QueueStorm-Investigator
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
echo "GOOGLE_API_KEY=AIza..." > backend/.env
echo "BACKEND_PORT=8000" >> backend/.env

# systemd unit, nginx config, certbot for TLS — see docs.render.com or
# digitalocean.com/community/tutorials for the 5-minute setup
```

CORS is already `allow_origins=["*"]`, so cross-origin (frontend and backend on different hosts) works out of the box.

---

## 14. Manual verification checklist

Before you submit / demo, confirm each item:

- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [ ] Browser at `http://localhost:8001` loads the form
- [ ] "Load sample case" → "Analyze ticket" returns a verdict panel with severity, evidence_verdict, department, agent_summary, etc.
- [ ] `python backend/test_cases.py` shows **16/16 passed**
- [ ] `git status` shows a clean tree (no `.env`, no `__pycache__`)
- [ ] `git log --oneline -1` shows a real commit, not a placeholder

If all six pass, you're done.

---

*Last verified: this repo's HEAD. If a step breaks, please open an issue with the exact command and the first 10 lines of error output.*
