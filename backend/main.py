"""
QueueStorm Investigator — Main FastAPI Application

A complaint investigation copilot API for digital finance support teams.
Analyzes customer complaints against transaction history to determine what
actually happened, using a hybrid Gemini + deterministic rules approach.

Endpoints:
  GET  /health         → {"status": "ok"}
  POST /analyze-ticket → Structured investigation verdict
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# Ensure sibling modules (models, evidence_engine, ...) are importable when
# uvicorn is launched as `uvicorn backend.main:app` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import TicketRequest, TicketResponse
from gemini_client import extract_facts
from fallback import extract_facts_deterministic
from evidence_engine import (
    find_relevant_transaction,
    compute_evidence_verdict,
    classify_case,
)
from response_builder import build_response_fields
from safety_validator import (
    sanitize_response,
    apply_injection_override,
)

# ─── Configuration ────────────────────────────────────────────────────────────

# Load .env from this file's directory (backend/.env) so the service is portable
# regardless of where uvicorn is launched from.
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("queuestorm")

# Port this service binds to. Override with BACKEND_PORT in backend/.env.
# Defaults to 8000 so existing local runs (uvicorn backend.main:app --port 8000)
# keep working with no env setup.
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
logger.info("QueueStorm backend port configured: %d", BACKEND_PORT)

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="QueueStorm Investigator",
    description="Complaint investigation copilot for digital finance support",
    version="1.0.0",
)

# ─── CORS (so the static frontend can call this API from a browser) ─────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # static demo frontend; tighten for production
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Error handlers ──────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """
    Override FastAPI's default 422 for missing required fields → 400.
    Only return 422 for schema-valid but semantically invalid input.
    """
    errors = exc.errors()
    # Check if any error is about a missing required field
    has_missing = any(e.get("type") in ("missing", "value_error.missing") for e in errors)

    # Check for empty complaint (semantic validation → 422)
    is_semantic = any(
        "complaint must not be empty" in str(e.get("msg", ""))
        for e in errors
    )

    if is_semantic:
        return JSONResponse(
            status_code=422,
            content={
                "error": "Semantically invalid input",
                "details": [
                    {"field": ".".join(str(l) for l in e.get("loc", [])), "message": e.get("msg", "")}
                    for e in errors
                ],
            },
        )

    status_code = 400 if has_missing else 400
    return JSONResponse(
        status_code=status_code,
        content={
            "error": "Invalid request",
            "details": [
                {"field": ".".join(str(l) for l in e.get("loc", [])), "message": e.get("msg", "")}
                for e in errors
            ],
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    """Catch-all: return safe 500 — never a stack trace, token, or secret."""
    logger.error("Unhandled exception: %s", str(exc))
    # Log the traceback to server logs only, never to the response
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Our team has been notified."},
    )


# ─── Health endpoint ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — must respond within 60s of process start."""
    return {"status": "ok"}


# ─── Main analysis endpoint ──────────────────────────────────────────────────

@app.options("/analyze-ticket")
async def analyze_ticket_options():
    """Explicit preflight handler so CORS middleware can attach headers."""
    return JSONResponse(status_code=200, content={})


@app.post("/analyze-ticket", response_model=TicketResponse)
async def analyze_ticket(ticket: TicketRequest):
    """
    Analyze a customer complaint against their transaction history.
    Returns a structured investigation verdict.
    """
    logger.info("Analyzing ticket: %s", ticket.ticket_id)

    # Serialize transaction history for processing
    transactions = None
    if ticket.transaction_history:
        transactions = [txn.model_dump() for txn in ticket.transaction_history]

    # ── Step 1: Extract facts (Gemini or fallback) ──
    extracted = await extract_facts(ticket.complaint, transactions)

    if extracted is None:
        logger.info("Gemini extraction failed, using deterministic fallback for %s", ticket.ticket_id)
        extracted = extract_facts_deterministic(ticket.complaint, transactions)

    logger.info("Extracted facts for %s: intent=%s, injection=%s",
                ticket.ticket_id,
                extracted.get("apparent_case_intent"),
                extracted.get("contains_injection_attempt"))

    # ── Step 2: Check for injection attempt ──
    is_injection = extracted.get("contains_injection_attempt", False)

    # ── Step 3: Evidence matching (deterministic) ──
    matched_txn, relevant_txn_id, match_reasons = find_relevant_transaction(
        extracted, transactions
    )

    # ── Step 4: Evidence verdict (deterministic) ──
    evidence_verdict, verdict_reasons = compute_evidence_verdict(
        extracted, matched_txn, transactions
    )

    # Merge reason codes
    reason_codes = list(set(match_reasons + verdict_reasons))

    # ── Step 5: Classification (deterministic) ──
    classification = classify_case(
        extracted, evidence_verdict, matched_txn, transactions
    )

    case_type = classification["case_type"]
    department = classification["department"]
    severity = classification["severity"]
    human_review = classification["human_review_required"]

    # ── Step 6: Build response text fields ──
    response_fields = build_response_fields(
        extracted=extracted,
        case_type=case_type,
        evidence_verdict=evidence_verdict,
        matched_txn=matched_txn,
        all_transactions=transactions,
        reason_codes=reason_codes,
    )

    # ── Step 7: Compute confidence ──
    confidence = _compute_confidence(evidence_verdict, matched_txn, is_injection, reason_codes)

    # ── Step 8: Assemble response ──
    response_dict: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,  # Echo exactly
        "relevant_transaction_id": relevant_txn_id,
        "evidence_verdict": evidence_verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": response_fields["agent_summary"],
        "recommended_next_action": response_fields["recommended_next_action"],
        "customer_reply": response_fields["customer_reply"],
        "human_review_required": human_review,
        "confidence": confidence,
        "reason_codes": reason_codes,
    }

    # ── Step 9: Apply injection override if needed ──
    if is_injection:
        response_dict = apply_injection_override(response_dict)

    # ── Step 10: Safety validation (final gate) ──
    response_dict = sanitize_response(response_dict)

    # ── Step 11: Validate through Pydantic and return ──
    validated = TicketResponse(**response_dict)
    logger.info("Completed analysis for %s: case=%s, verdict=%s, dept=%s",
                ticket.ticket_id, case_type, evidence_verdict, department)

    return validated


# ─── Confidence computation ──────────────────────────────────────────────────

def _compute_confidence(
    verdict: str,
    matched_txn: dict | None,
    is_injection: bool,
    reason_codes: list[str],
) -> float:
    """Compute a confidence score (0.0 - 1.0)."""
    if is_injection:
        return 0.95  # High confidence in injection detection

    base = 0.5

    # Evidence quality
    if verdict == "consistent" and matched_txn:
        base += 0.3
    elif verdict == "inconsistent" and matched_txn:
        base += 0.2
    elif verdict == "insufficient_data":
        base -= 0.1

    # Ambiguity penalty
    if "ambiguous_match" in reason_codes:
        base -= 0.15
    if "needs_clarification" in reason_codes:
        base -= 0.1
    if "weak_match" in reason_codes:
        base -= 0.1

    # Strong match bonus
    if "transaction_match" in reason_codes and matched_txn:
        base += 0.1

    return round(max(0.1, min(1.0, base)), 2)


# ─── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # BACKEND_PORT is set from .env above; defaults to 8000 if unset.
    uvicorn.run("main:app", host="0.0.0.0", port=BACKEND_PORT, reload=True)
