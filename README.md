# QueueStorm-Investigator

**SUST CSE Carnival 2026 — Codex Community Hackathon — Online Preliminary**

An internal copilot API for a digital finance support team. Given a customer complaint and transaction history, it investigates what *actually happened* — which may differ from what the customer claims — and returns a structured JSON verdict.

> 📘 **First time here?** Read [`SETUP.md`](SETUP.md) for the full end-to-end install + run + troubleshoot recipe (Windows-first, macOS / Linux notes appended). This README is the tour; SETUP.md is the cookbook.

---

## Submission Compliance

| Requirement | Where it lives |
|---|---|
| `GET /health` | [`backend/main.py`](backend/main.py) → returns `{"status":"ok"}` within 60s of process start |
| `POST /analyze-ticket` | [`backend/main.py`](backend/main.py) — single ticket in, single structured response out |
| Setup & Run instructions | [Quick Start](#quick-start) below |
| AI / Model usage | [AI Model Usage](#ai-model-usage) below |
| Safety logic | [Safety Logic](#safety-logic) below |
| Limitations | [Assumptions and Known Limitations](#assumptions-and-known-limitations) below |
| No real secrets in repo | `.env` is gitignored (see [`.gitignore`](.gitignore)); `.env.example` ships with a placeholder only |
| No real customer/payment data | Sample cases use synthetic `[redacted]-…` / `MERCHANT-…` / `AGENT-…` placeholders; the API never persists inputs |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Google AI Studio API key ([get one free](https://aistudio.google.com/))

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd Complaint-Investigator

# Install dependencies
pip install -r backend/requirements.txt

# Set up environment
cp backend/.env.example backend/.env
# Edit backend/.env and add your Google AI Studio API key
```

### Run

```bash
# From the project root
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Test

```bash
# Health check
curl http://localhost:8000/health

# Run sample cases (run from project root or from backend/)
python backend/test_cases.py
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Framework | FastAPI + Uvicorn |
| Validation | Pydantic (Literal enums for all enum fields) |
| LLM | Google AI Studio — Gemini (auto-selected, see [AI Model Usage](#ai-model-usage)) |
| HTTP Client | httpx |
| Environment | python-dotenv |

---

## Architecture

```
POST /analyze-ticket
        │
        ▼
┌──────────────────┐
│ Pydantic Input   │ → 400 (missing fields) / 422 (empty complaint)
│ Validation       │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌───────────────────┐
│ Gemini Extraction│────►│ Deterministic     │ (fallback on any error)
│ (NLU only, 10s   │     │ Keyword/Regex     │
│  timeout)        │     │ Extraction        │
└──────┬───────────┘     └───────┬───────────┘
       │                         │
       ▼                         ▼
┌──────────────────────────────────┐
│ Evidence Matching Engine         │ ← Deterministic Python rules
│ • Transaction scoring            │
│ • Verdict computation            │
│ • Case classification            │
└──────┬───────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│ Response Builder                 │ ← Template-based, Bangla support
│ • agent_summary                  │
│ • customer_reply                 │
│ • recommended_next_action        │
└──────┬───────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│ Safety Validator                 │ ← Runs on EVERY response
│ • No credential requests         │
│ • No promissory refund language  │
│ • No third-party contacts        │
│ • Injection override             │
└──────┬───────────────────────────┘
       │
       ▼
   200 JSON Response
```

### Hybrid Approach (Gemini + Deterministic Rules)

- **Gemini 2.0 Flash** is used **only** for natural language understanding — extracting structured facts from free-text complaints (especially Bangla/Banglish)
- **All verdict/enum decisions are made deterministically** by Python rules — the LLM never decides `evidence_verdict`, `case_type`, or any enum value directly
- **Deterministic fallback** activates automatically on any Gemini failure (timeout, quota, network error, bad JSON)

---

## AI Model Usage

| Field | Value |
|---|---|
| Provider | Google AI Studio (Gemini free tier, no billing required) |
| Default model | Auto-selected at first use from `gemini-2.5-flash`, `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-2.0-flash`, `gemini-2.0-flash-lite` (probed in order, first that responds wins) |
| Override | Set `GEMINI_MODEL=<name>` in `backend/.env` to force a specific model |
| Why chosen | Free tier, no billing; fast enough for p95 < 30 s; native Bangla/Banglish understanding; the probe-and-pin logic makes the service resilient when individual models hit quota=0 on a project |
| Initialization | Lazy — model is only loaded on the first `/analyze-ticket` call, never at app startup (so the service stays healthy even when the LLM is unavailable) |
| Timeout | 10 seconds per call (`asyncio.wait_for`) — falls back to deterministic extraction on timeout |
| Usage | NLU extraction only — structured fact extraction from complaint text |
| Trust level | Gemini output is **never** trusted directly for enums or customer-facing text; all values are validated against explicit allow-lists in [`backend/gemini_client.py`](backend/gemini_client.py) |
| Failure mode | Any error (timeout, 429, bad JSON, network) → `extract_facts` returns `None` → [`backend/fallback.py`](backend/fallback.py) runs deterministic regex/keyword extraction |
| Persistence | The API stores nothing — no DB, no logs of customer text to disk |

---

## Safety Logic

A dedicated `safety_validator.py` module runs on **every response** before it is returned:

1. **Credential Request Check** — Regex scanning for PIN/OTP/password/card number requests in `customer_reply`
2. **Promissory Refund Check** — Detects and replaces "we will refund", "you will receive", "we guarantee" in both `customer_reply` and `recommended_next_action`
3. **Third-Party Contact Check** — Blocks external phone numbers, URLs, non-official channel references
4. **Injection Detection** — Complaints containing system-manipulation attempts are reclassified as `phishing_or_social_engineering` with `human_review_required: true`

The safety validator is a **separate, testable Python function** — not just prompt text.

---

## Evidence Reasoning (The Investigator Twist)

The core investigation logic in `evidence_engine.py`:

1. **Transaction scoring** — Each transaction in history is scored on: amount match, counterparty match, type match, status relevance, recency
2. **Ambiguity detection** — If top two candidates score within 85% of each other, returns `insufficient_data` instead of guessing
3. **Inconsistency detection** — e.g., repeated past transfers to the same "wrong" recipient → `inconsistent`
4. **Special case handling** — Phishing reports with empty history, vague complaints, duplicate payments within seconds

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns `{"status":"ok"}` |
| POST | `/analyze-ticket` | Analyzes one complaint, returns structured verdict |

---

## Assumptions and Known Limitations

- **Language**: Gemini handles Bangla/Banglish natively; the deterministic fallback uses keyword matching for common Bangla terms but is less capable
- **Amount matching**: Uses exact match with a 10% tolerance band
- **Time matching**: Currently uses recency bonus rather than exact time parsing from complaint text
- **High-value threshold**: ≥10,000 BDT triggers human review
- **Duplicate detection**: Two payments to the same biller within 5 minutes with the same amount are flagged as duplicates

---

## Run Command

```bash
# From the project root, after installing backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## Project Layout

```
Complaint-Investigator/
├── backend/                # FastAPI service
│   ├── main.py             # entrypoint
│   ├── models.py           # Pydantic request/response schemas
│   ├── evidence_engine.py  # deterministic evidence matcher
│   ├── fallback.py         # regex/keyword NLU fallback
│   ├── gemini_client.py    # Gemini 2.0 Flash wrapper
│   ├── response_builder.py # verdict + reply templating
│   ├── safety_validator.py # post-response safety checks
│   ├── test_cases.py       # 10-case + error-handling test suite
│   ├── requirements.txt
│   └── .env.example
├── frontend/               # static HTML/CSS/JS UI
├── SUST_Preli_Sample_Cases.json
├── README.md
└── SETUP.md                # full install + run + troubleshoot guide
```

---

## Deliverables Checklist

- [x] GitHub repo with all code
- [x] `POST /analyze-ticket` endpoint conforming to the contract
- [x] `GET /health` endpoint
- [x] `README.md` with setup, run, tech stack, AI approach, safety logic
- [x] `requirements.txt`
- [x] `.env.example`
- [x] Sample test output (`test_results.json` — run `python test_cases.py`)
- [x] MODELS section in README
