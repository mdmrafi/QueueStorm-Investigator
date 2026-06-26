"""
Post-generation safety validator.
Runs on every response before it is returned — regardless of whether fields
were produced by Gemini or the deterministic fallback.

Checks:
  1. credential_request  — PIN / OTP / password / card number in customer_reply
  2. promissory_refund   — "we will refund" / "you will receive" etc.
  3. third_party_contact — phone numbers, external URLs, non-official channels
  4. injection_flag      — Gemini flagged contains_injection_attempt
"""

from __future__ import annotations

import re
from typing import Any


# ─── Patterns ─────────────────────────────────────────────────────────────────

# Case-insensitive patterns that must NOT appear in customer_reply
_CREDENTIAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:share|provide|send|give|enter|confirm|verify|tell)\b.*\b(?:pin|otp|password|card\s*number)\b", re.IGNORECASE),
    re.compile(r"\b(?:pin|otp|password|card\s*number)\b.*\b(?:share|provide|send|give|enter|confirm|verify|tell)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+your\s+(?:pin|otp|password)\b", re.IGNORECASE),
    re.compile(r"\benter\s+your\s+(?:pin|otp|password|card\s*number)\b", re.IGNORECASE),
    re.compile(r"\b(?:need|require)\s+your\s+(?:pin|otp|password|card\s*number)\b", re.IGNORECASE),
]

_PROMISSORY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwe\s+will\s+refund\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+reverse\b", re.IGNORECASE),
    re.compile(r"\byou\s+will\s+(?:receive|get)\s+(?:your|the|a)?\s*(?:money|refund|amount)\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(?:guarantee|promise|assure)\b", re.IGNORECASE),
    re.compile(r"\byour\s+(?:money|amount|refund)\s+(?:will|has)\s+been\s+(?:refunded|returned|reversed)\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(?:have|has)\s+(?:refunded|reversed|returned)\b", re.IGNORECASE),
    re.compile(r"\bwe\s+will\s+(?:unblock|recover|restore)\b", re.IGNORECASE),
    re.compile(r"\byour\s+account\s+(?:will|has)\s+been\s+(?:unblocked|restored)\b", re.IGNORECASE),
]

_THIRD_PARTY_PATTERNS: list[re.Pattern] = [
    # Phone numbers that aren't transaction IDs
    re.compile(r"(?:call|contact|reach|dial|phone)\s+[\+\d][\d\-\s]{7,}", re.IGNORECASE),
    # External URLs (not official support)
    re.compile(r"(?:visit|go\s+to|open|check)\s+(?:https?://|www\.)", re.IGNORECASE),
    # "contact XYZ" where XYZ is not "us" / "our support" / "official"
    re.compile(r"\bcontact\s+(?!us\b|our\b|the\s+(?:merchant|support|team|department|official))[\w]+", re.IGNORECASE),
]


# ─── Safe replacement templates ──────────────────────────────────────────────

_SAFE_REPLY_SUFFIX = " Please do not share your PIN or OTP with anyone."

_SAFE_REFUND_REPLACEMENT = "any eligible amount will be returned through official channels"


# ─── Public API ───────────────────────────────────────────────────────────────

class SafetyViolation:
    """A single detected safety issue."""

    def __init__(self, rule: str, field: str, matched_text: str) -> None:
        self.rule = rule
        self.field = field
        self.matched_text = matched_text

    def __repr__(self) -> str:
        return f"SafetyViolation(rule={self.rule!r}, field={self.field!r}, match={self.matched_text!r})"


def validate_response(response: dict[str, Any]) -> list[SafetyViolation]:
    """
    Scan a response dict for safety violations.
    Returns a list of SafetyViolation objects (empty if clean).
    """
    violations: list[SafetyViolation] = []
    customer_reply = response.get("customer_reply", "")
    next_action = response.get("recommended_next_action", "")

    # 1. Credential request check (customer_reply only)
    for pattern in _CREDENTIAL_PATTERNS:
        m = pattern.search(customer_reply)
        if m:
            violations.append(SafetyViolation("credential_request", "customer_reply", m.group()))

    # 2. Promissory refund check (customer_reply + recommended_next_action)
    for field_name, text in [("customer_reply", customer_reply), ("recommended_next_action", next_action)]:
        for pattern in _PROMISSORY_PATTERNS:
            m = pattern.search(text)
            if m:
                violations.append(SafetyViolation("promissory_refund", field_name, m.group()))

    # 3. Third-party contact check (customer_reply only)
    for pattern in _THIRD_PARTY_PATTERNS:
        m = pattern.search(customer_reply)
        if m:
            violations.append(SafetyViolation("third_party_contact", "customer_reply", m.group()))

    return violations


def sanitize_response(response: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and sanitize a response dict.
    If violations are found, fix the offending fields in-place.
    Returns the (possibly modified) response.
    """
    violations = validate_response(response)
    if not violations:
        return response

    customer_reply = response.get("customer_reply", "")
    next_action = response.get("recommended_next_action", "")

    for v in violations:
        if v.rule == "credential_request":
            # Replace the entire customer_reply with a safe version
            customer_reply = _rebuild_safe_reply(response)
            break  # rebuilt the whole reply, no need to patch further

    # Patch promissory refund language
    for v in violations:
        if v.rule == "promissory_refund":
            if v.field == "customer_reply":
                customer_reply = _replace_promissory(customer_reply)
            elif v.field == "recommended_next_action":
                next_action = _replace_promissory(next_action)

    # Ensure the PIN/OTP safety reminder is present
    if not re.search(r"\b(?:PIN|OTP)\b", customer_reply):
        customer_reply = customer_reply.rstrip(". ") + "." + _SAFE_REPLY_SUFFIX

    response["customer_reply"] = customer_reply
    response["recommended_next_action"] = next_action
    return response


def apply_injection_override(response: dict[str, Any]) -> dict[str, Any]:
    """
    If the Gemini extraction flagged an injection attempt,
    override the response to treat it as phishing/social engineering.
    """
    response["case_type"] = "phishing_or_social_engineering"
    response["department"] = "fraud_risk"
    response["severity"] = "critical"
    response["human_review_required"] = True
    if response.get("reason_codes") is None:
        response["reason_codes"] = []
    if "injection_attempt" not in response["reason_codes"]:
        response["reason_codes"].append("injection_attempt")
    return response


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _rebuild_safe_reply(response: dict[str, Any]) -> str:
    """Build a generic safe reply when the original was contaminated."""
    ticket_id = response.get("ticket_id", "your ticket")
    txn_id = response.get("relevant_transaction_id")
    txn_ref = f" regarding transaction {txn_id}" if txn_id else ""
    return (
        f"Thank you for reaching out{txn_ref}. "
        f"We have received your concern (ticket {ticket_id}) and our team will review it. "
        f"Any eligible resolution will be handled through official channels."
        + _SAFE_REPLY_SUFFIX
    )


def _replace_promissory(text: str) -> str:
    """Replace promissory refund/reversal language with safe alternatives."""
    for pattern in _PROMISSORY_PATTERNS:
        text = pattern.sub(_SAFE_REFUND_REPLACEMENT, text)
    return text
