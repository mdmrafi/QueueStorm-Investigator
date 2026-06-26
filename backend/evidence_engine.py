"""
Evidence matching and verdict computation engine.

This is the core "Investigator Twist" — the highest-weighted skill (35 pts).
All logic here is deterministic Python rules. Gemini never decides verdicts.

Steps:
  1. Find the relevant transaction in history (or null if ambiguous/none).
  2. Compute evidence_verdict (consistent / inconsistent / insufficient_data).
  3. Classify case_type, department, severity, human_review_required.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# ─── Transaction matching ─────────────────────────────────────────────────────

def find_relevant_transaction(
    extracted: dict[str, Any],
    transactions: list[dict[str, Any]] | None,
) -> tuple[Optional[dict[str, Any]], Optional[str], list[str]]:
    """
    Find the best-matching transaction from history based on extracted claims.

    Returns:
        (matched_transaction_dict, transaction_id, reason_codes)
        If ambiguous or no match: (None, None, reason_codes)
    """
    if not transactions:
        return None, None, ["no_transaction_history"]

    claimed_amount = extracted.get("claimed_amount")
    claimed_counterparty = extracted.get("claimed_counterparty")
    claimed_type = extracted.get("claimed_transaction_type")
    intent = extracted.get("apparent_case_intent", "other")

    scored: list[tuple[float, dict[str, Any]]] = []

    for txn in transactions:
        score = 0.0
        txn_amount = txn.get("amount", 0)
        txn_counterparty = txn.get("counterparty", "")
        txn_type = txn.get("type", "")
        txn_status = txn.get("status", "")

        # Amount match (most important signal)
        if claimed_amount is not None:
            if txn_amount == claimed_amount:
                score += 4.0
            elif abs(txn_amount - claimed_amount) / max(claimed_amount, 1) < 0.1:
                score += 2.0  # Close match (within 10%)

        # Counterparty match
        if claimed_counterparty and txn_counterparty:
            if _normalize_phone(claimed_counterparty) == _normalize_phone(txn_counterparty):
                score += 3.0
            elif claimed_counterparty.lower() in txn_counterparty.lower():
                score += 1.5

        # Transaction type match
        if claimed_type and txn_type:
            if claimed_type == txn_type:
                score += 2.0
            # Infer type from intent
            elif _intent_matches_type(intent, txn_type):
                score += 1.0

        # Intent-type alignment bonus
        if _intent_matches_type(intent, txn_type):
            score += 1.0

        # Status relevance bonus
        if intent == "payment_failed" and txn_status == "failed":
            score += 2.0
        elif intent == "agent_cash_in_issue" and txn_status == "pending":
            score += 1.5
        elif intent == "merchant_settlement_delay" and txn_status == "pending":
            score += 1.5

        # Recency bonus (more recent = slightly more likely to be relevant)
        try:
            ts = datetime.fromisoformat(txn.get("timestamp", "").replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_hours < 24:
                score += 0.5
            elif age_hours < 72:
                score += 0.2
        except (ValueError, TypeError):
            pass

        if score > 0:
            scored.append((score, txn))

    if not scored:
        return None, None, ["no_matching_transaction"]

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_txn = scored[0]

    # Check for ambiguity — if top two scores are very close
    if len(scored) >= 2:
        second_score = scored[1][0]
        if best_score > 0 and second_score / best_score > 0.85:
            # Special case for duplicate payment: we EXPECT multiple identical matches
            if intent == "duplicate_payment":
                try:
                    # Sort top scoring txns by timestamp descending (most recent first)
                    top_txns = [t for s, t in scored if s >= second_score]
                    top_txns.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
                    best_txn = top_txns[0]
                    return best_txn, best_txn.get("transaction_id"), ["transaction_match", "duplicate_candidate"]
                except Exception:
                    pass
            # Too close — ambiguous
            return None, None, ["ambiguous_match", "needs_clarification"]

    if best_score < 2.0:
        # Score too low to be confident
        return None, None, ["weak_match", "needs_clarification"]

    return best_txn, best_txn.get("transaction_id"), ["transaction_match"]


# ─── Evidence verdict computation ─────────────────────────────────────────────

def compute_evidence_verdict(
    extracted: dict[str, Any],
    matched_txn: Optional[dict[str, Any]],
    all_transactions: list[dict[str, Any]] | None,
) -> tuple[str, list[str]]:
    """
    Compute evidence_verdict by comparing extracted claims against transaction data.

    Returns:
        (verdict_string, additional_reason_codes)
    """
    intent = extracted.get("apparent_case_intent", "other")

    # Special case: phishing report with no transaction involved
    if intent == "phishing_or_social_engineering":
        if not all_transactions:
            return "insufficient_data", ["phishing", "no_transaction_needed"]
        return "insufficient_data", ["phishing"]

    # No match found
    if matched_txn is None:
        return "insufficient_data", ["no_evidence_match"]

    claimed_amount = extracted.get("claimed_amount")
    txn_amount = matched_txn.get("amount", 0)
    txn_status = matched_txn.get("status", "")
    txn_counterparty = matched_txn.get("counterparty", "")
    txn_type = matched_txn.get("type", "")

    reasons: list[str] = []

    # ── Wrong transfer checks ──
    if intent == "wrong_transfer":
        # Check if the recipient is someone they send to regularly
        if all_transactions and txn_counterparty:
            prior_to_same = sum(
                1 for t in all_transactions
                if t.get("counterparty") == txn_counterparty
                and t.get("transaction_id") != matched_txn.get("transaction_id")
                and t.get("type") in ("transfer", "payment")
            )
            if prior_to_same >= 2:
                reasons.append("established_recipient_pattern")
                reasons.append("evidence_inconsistent")
                return "inconsistent", reasons

        # Amount matches, completed transfer → consistent with wrong transfer
        if claimed_amount and txn_amount == claimed_amount and txn_status == "completed":
            reasons.append("transaction_match")
            return "consistent", reasons

        # Amount close enough
        if claimed_amount and txn_status == "completed":
            reasons.append("transaction_match")
            return "consistent", reasons

        return "consistent", ["transaction_match"]

    # ── Payment failed checks ──
    if intent == "payment_failed":
        if txn_status == "failed":
            reasons.append("payment_failed")
            if claimed_amount and txn_amount == claimed_amount:
                reasons.append("potential_balance_deduction")
            return "consistent", reasons
        elif txn_status == "completed":
            # Customer claims failed but status shows completed — might still be
            # consistent if they claim balance was deducted
            reasons.append("payment_status_completed")
            return "consistent", reasons
        return "consistent", ["payment_status_check"]

    # ── Duplicate payment checks ──
    if intent == "duplicate_payment":
        if all_transactions and claimed_amount:
            duplicates = [
                t for t in all_transactions
                if t.get("amount") == claimed_amount
                and t.get("type") == "payment"
                and t.get("status") == "completed"
            ]
            if len(duplicates) >= 2:
                # Check if they're close in time (within 5 minutes)
                try:
                    times = sorted([
                        datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
                        for d in duplicates
                    ])
                    for i in range(len(times) - 1):
                        if (times[i + 1] - times[i]) < timedelta(minutes=5):
                            reasons.extend(["duplicate_payment", "biller_verification_required"])
                            return "consistent", reasons
                except (ValueError, KeyError):
                    pass
                reasons.extend(["duplicate_payment", "biller_verification_required"])
                return "consistent", reasons
        return "insufficient_data", ["possible_duplicate"]

    # ── Refund request checks ──
    if intent == "refund_request":
        if txn_status == "completed":
            reasons.append("merchant_policy_dependent")
            return "consistent", reasons
        return "consistent", ["refund_request"]

    # ── Merchant settlement delay ──
    if intent == "merchant_settlement_delay":
        if txn_status == "pending":
            reasons.extend(["merchant_settlement", "delay", "pending"])
            return "consistent", reasons
        if txn_status == "completed":
            reasons.extend(["merchant_settlement", "already_settled"])
            return "inconsistent", reasons
        return "consistent", ["merchant_settlement"]

    # ── Agent cash-in issue ──
    if intent == "agent_cash_in_issue":
        if txn_status == "pending":
            reasons.extend(["agent_cash_in", "pending_transaction", "agent_ops"])
            return "consistent", reasons
        if txn_status == "completed":
            reasons.extend(["agent_cash_in", "status_completed"])
            return "inconsistent", reasons
        return "consistent", ["agent_cash_in"]

    # ── Default: generic check ──
    return "consistent", ["general_match"]


# ─── Classification engine ───────────────────────────────────────────────────

# Department routing map
_DEPARTMENT_MAP: dict[str, str] = {
    "wrong_transfer": "dispute_resolution",
    "payment_failed": "payments_ops",
    "refund_request": "customer_support",
    "duplicate_payment": "payments_ops",
    "merchant_settlement_delay": "merchant_operations",
    "agent_cash_in_issue": "agent_operations",
    "phishing_or_social_engineering": "fraud_risk",
    "other": "customer_support",
}


def classify_case(
    extracted: dict[str, Any],
    evidence_verdict: str,
    matched_txn: Optional[dict[str, Any]],
    all_transactions: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    Determine case_type, department, severity, and human_review_required.

    Returns a dict with these four fields.
    """
    intent = extracted.get("apparent_case_intent", "other")

    # Fix for ambiguous wrong transfers (like "sent to brother" without "wrong" keyword)
    if intent == "other" and extracted.get("claimed_transaction_type") == "transfer":
        intent = "wrong_transfer"

    # Map intent to case_type (they use the same enum values)
    case_type = intent

    # Department from the mapping table
    department = _DEPARTMENT_MAP.get(case_type, "customer_support")

    # Override department for contested refund requests
    if case_type == "refund_request" and evidence_verdict == "inconsistent":
        department = "dispute_resolution"

    # Severity computation
    severity = _compute_severity(
        case_type, evidence_verdict, extracted, matched_txn
    )

    # Human review logic
    human_review = _needs_human_review(
        case_type, evidence_verdict, severity, extracted, matched_txn
    )

    return {
        "case_type": case_type,
        "department": department,
        "severity": severity,
        "human_review_required": human_review,
    }


def _compute_severity(
    case_type: str,
    verdict: str,
    extracted: dict[str, Any],
    matched_txn: Optional[dict[str, Any]],
) -> str:
    """Determine severity level."""
    amount = extracted.get("claimed_amount") or (
        matched_txn.get("amount") if matched_txn else None
    )

    # Phishing is always critical
    if case_type == "phishing_or_social_engineering":
        return "critical"

    # High value transactions (≥10,000 BDT), exempting merchant settlements
    if amount and amount >= 10000 and case_type != "merchant_settlement_delay":
        return "high"

    # Specific case type defaults
    if case_type == "wrong_transfer":
        if verdict == "inconsistent" or verdict == "insufficient_data":
            return "medium"
        return "high"

    if case_type == "payment_failed":
        return "high"

    if case_type == "duplicate_payment":
        return "high"

    if case_type == "agent_cash_in_issue":
        if matched_txn and matched_txn.get("status") == "pending":
            return "high"
        return "medium"

    if case_type == "merchant_settlement_delay":
        return "medium"

    if case_type == "refund_request":
        return "low"

    if verdict == "insufficient_data":
        return "low"

    return "low"


def _needs_human_review(
    case_type: str,
    verdict: str,
    severity: str,
    extracted: dict[str, Any],
    matched_txn: Optional[dict[str, Any]],
) -> bool:
    """Determine if the case needs human review."""
    # Always escalate these
    if case_type == "phishing_or_social_engineering":
        return True

    # Disputes always need review, unless we don't have enough data to even start one
    if case_type == "wrong_transfer":
        if verdict == "insufficient_data":
            return False
        return True

    # Inconsistent evidence needs review
    if verdict == "inconsistent":
        return True

    # High-value cases (≥10,000 BDT), exempting merchant settlements
    amount = extracted.get("claimed_amount") or (
        matched_txn.get("amount") if matched_txn else None
    )
    if amount and amount >= 10000 and case_type != "merchant_settlement_delay":
        return True

    # Critical severity
    if severity == "critical":
        return True

    # Duplicate payments need biller verification
    if case_type == "duplicate_payment":
        return True

    # Agent cash-in pending needs investigation
    if case_type == "agent_cash_in_issue" and matched_txn:
        if matched_txn.get("status") == "pending":
            return True

    # Injection attempts
    if extracted.get("contains_injection_attempt"):
        return True

    return False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Normalize a phone number for comparison."""
    digits = re.sub(r"[^\d]", "", phone)
    # Bangladesh numbers: +880XXXXXXXXXX or 01XXXXXXXXX
    if digits.startswith("880") and len(digits) == 13:
        return digits
    if digits.startswith("0") and len(digits) == 11:
        return "880" + digits[1:]
    return digits


def _intent_matches_type(intent: str, txn_type: str) -> bool:
    """Check if a case intent aligns with a transaction type."""
    mapping = {
        "wrong_transfer": {"transfer"},
        "payment_failed": {"payment"},
        "refund_request": {"payment", "refund"},
        "duplicate_payment": {"payment"},
        "merchant_settlement_delay": {"settlement"},
        "agent_cash_in_issue": {"cash_in"},
    }
    return txn_type in mapping.get(intent, set())
