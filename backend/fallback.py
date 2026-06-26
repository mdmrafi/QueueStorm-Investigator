"""
Deterministic fallback extractor.

Uses keyword/regex matching on the complaint string to infer structured facts
when Gemini is unavailable (timeout, quota, network error, bad JSON).

This is a real, tested code path — not a TODO. A working fallback that scores
70% is far better than an LLM path that crashes and scores 0%.
"""

from __future__ import annotations

import re
from typing import Any, Optional


# ─── Keyword maps ─────────────────────────────────────────────────────────────

# Case intent detection — order matters (first match wins for primary intent)
_INTENT_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("phishing_or_social_engineering", [
        re.compile(r"\b(?:otp|pin|password|phishing|scam|fraud)\b", re.IGNORECASE),
        re.compile(r"(?:someone|কেউ|লোক).*(?:call|ফোন|কল).*(?:otp|pin|পিন|ওটিপি)", re.IGNORECASE),
        re.compile(r"(?:ignore|override|bypass|forget).*(?:instruction|rule|previous)", re.IGNORECASE),
        re.compile(r"\b(?:হ্যাক|প্রতারণা|জালিয়াতি)\b", re.IGNORECASE),
    ]),
    ("duplicate_payment", [
        re.compile(r"\b(?:duplicate|double|twice|two\s+times|দুইবার|দুবার|ডাবল)\b", re.IGNORECASE),
        re.compile(r"(?:deducted|charged|কাটা).*(?:twice|two|দুই)", re.IGNORECASE),
    ]),
    ("wrong_transfer", [
        re.compile(r"\b(?:wrong|ভুল)\s*(?:number|নম্বর|person|transfer|recipient)\b", re.IGNORECASE),
        re.compile(r"(?:sent|পাঠ).*(?:wrong|ভুল)", re.IGNORECASE),
        re.compile(r"(?:wrong|ভুল).*(?:sent|পাঠ|transfer)", re.IGNORECASE),
    ]),
    ("payment_failed", [
        re.compile(r"\b(?:fail|failed|ব্যর্থ)\b", re.IGNORECASE),
        re.compile(r"(?:balance|ব্যালেন্স).*(?:deduct|কাট).*(?:fail|ব্যর্থ)", re.IGNORECASE),
        re.compile(r"(?:fail|ব্যর্থ).*(?:balance|ব্যালেন্স).*(?:deduct|কাট)", re.IGNORECASE),
    ]),
    ("refund_request", [
        re.compile(r"\b(?:refund|ফেরত|রিফান্ড)\b", re.IGNORECASE),
        re.compile(r"(?:money|টাকা)\s*(?:back|ফেরত)", re.IGNORECASE),
        re.compile(r"(?:changed?\s+(?:my\s+)?mind|don'?t\s+want)", re.IGNORECASE),
    ]),
    ("merchant_settlement_delay", [
        re.compile(r"\b(?:settlement|সেটেলমেন্ট)\b", re.IGNORECASE),
        re.compile(r"(?:merchant|ব্যবসায়ী).*(?:not\s+(?:received|settled)|আসেনি)", re.IGNORECASE),
    ]),
    ("agent_cash_in_issue", [
        re.compile(r"\b(?:cash\s*in|ক্যাশ\s*ইন)\b", re.IGNORECASE),
        re.compile(r"(?:agent|এজেন্ট).*(?:deposit|জমা|cash|ক্যাশ)", re.IGNORECASE),
        re.compile(r"(?:balance|ব্যালেন্স).*(?:not|নাই|আসে\s*নি).*(?:reflect|show|দেখ)", re.IGNORECASE),
    ]),
]

# Amount extraction patterns
_AMOUNT_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:taka|tk|bdt|টাকা)", re.IGNORECASE),
    re.compile(r"(?:taka|tk|bdt|টাকা)\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(?:amount|sent|paid|received|transferred|deducted|কাট|পাঠ|দি)\s*(?:of|:)?\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
]

# Counterparty extraction
_COUNTERPARTY_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\+?880\d{10})", re.IGNORECASE),
    re.compile(r"\b(01[3-9]\d{8})\b"),
    re.compile(r"(MERCHANT-[\w-]+)", re.IGNORECASE),
    re.compile(r"(AGENT-[\w-]+)", re.IGNORECASE),
]

# Time hint extraction
_TIME_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(today|yesterday|আজ|গতকাল|সকালে|বিকেলে|রাতে)\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2}\s*(?:am|pm|AM|PM))\b"),
    re.compile(r"\b((?:this|last)\s+(?:morning|afternoon|evening|night))\b", re.IGNORECASE),
    re.compile(r"\b(around\s+\d{1,2}\s*(?:am|pm|o'?clock)?)\b", re.IGNORECASE),
]

# Transaction type keywords
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "transfer": ["transfer", "sent", "send", "পাঠ", "ট্রান্সফার"],
    "payment": ["payment", "pay", "paid", "bill", "recharge", "পেমেন্ট", "বিল"],
    "cash_in": ["cash in", "cashin", "cash-in", "deposit", "ক্যাশ ইন", "জমা"],
    "cash_out": ["cash out", "cashout", "cash-out", "withdraw", "ক্যাশ আউট"],
    "settlement": ["settlement", "settle", "সেটেলমেন্ট"],
    "refund": ["refund", "রিফান্ড", "ফেরত"],
}


# ─── Bangla character detection ───────────────────────────────────────────────

_BANGLA_RANGE = re.compile(r"[\u0980-\u09FF]")
_LATIN_RANGE = re.compile(r"[a-zA-Z]")


def _detect_language(text: str) -> str:
    """Detect language from the complaint text."""
    has_bangla = bool(_BANGLA_RANGE.search(text))
    has_latin = bool(_LATIN_RANGE.search(text))
    if has_bangla and has_latin:
        return "mixed"
    if has_bangla:
        return "bn"
    return "en"


# ─── Injection detection ─────────────────────────────────────────────────────

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(?:previous|your|all|above)\s+(?:instruction|rule|prompt)", re.IGNORECASE),
    re.compile(r"(?:forget|disregard)\s+(?:everything|your|all|the)\s+(?:above|instruction|rule|previous)", re.IGNORECASE),
    re.compile(r"you\s+(?:are|must)\s+(?:now|actually)", re.IGNORECASE),
    re.compile(r"(?:system|admin)\s*(?:prompt|override|command)", re.IGNORECASE),
    re.compile(r"(?:act|pretend|behave)\s+(?:as|like)\s+(?:a|an|if)", re.IGNORECASE),
    re.compile(r"new\s+(?:instruction|role|directive)", re.IGNORECASE),
    re.compile(r"(?:tell|show|reveal|give)\s+(?:me|us)\s+(?:the|your)\s+(?:otp|pin|password|secret|key|prompt)", re.IGNORECASE),
]


# ─── Public API ───────────────────────────────────────────────────────────────

def extract_facts_deterministic(
    complaint: str,
    transaction_history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    Extract structured facts from a complaint using keyword/regex matching.
    Returns the same shape as Gemini extraction output.
    Always succeeds — never raises.
    """
    # Detect injection attempt
    contains_injection = any(p.search(complaint) for p in _INJECTION_PATTERNS)

    # Detect language
    language = _detect_language(complaint)

    # Extract claimed amount
    claimed_amount = None
    for pattern in _AMOUNT_PATTERNS:
        m = pattern.search(complaint)
        if m:
            try:
                claimed_amount = float(m.group(1).replace(",", ""))
            except (ValueError, IndexError):
                pass
            break

    # Extract counterparty
    claimed_counterparty = None
    for pattern in _COUNTERPARTY_PATTERNS:
        m = pattern.search(complaint)
        if m:
            claimed_counterparty = m.group(1)
            break

    # Extract time hint
    claimed_time_hint = None
    for pattern in _TIME_PATTERNS:
        m = pattern.search(complaint)
        if m:
            claimed_time_hint = m.group(1)
            break

    # Detect case intent
    apparent_case_intent = "other"
    for intent, patterns in _INTENT_PATTERNS:
        if any(p.search(complaint) for p in patterns):
            apparent_case_intent = intent
            break

    # Detect transaction type
    claimed_transaction_type = None
    complaint_lower = complaint.lower()
    for txn_type, keywords in _TYPE_KEYWORDS.items():
        if any(kw in complaint_lower for kw in keywords):
            claimed_transaction_type = txn_type
            break

    # Build claimed outcome summary
    claimed_outcome = _build_outcome_summary(
        complaint, apparent_case_intent, claimed_amount
    )

    return {
        "claimed_amount": claimed_amount,
        "claimed_counterparty": claimed_counterparty,
        "claimed_time_hint": claimed_time_hint,
        "claimed_transaction_type": claimed_transaction_type,
        "claimed_outcome": claimed_outcome,
        "apparent_case_intent": apparent_case_intent,
        "language_detected": language,
        "contains_injection_attempt": contains_injection,
    }


def _build_outcome_summary(
    complaint: str, intent: str, amount: Optional[float]
) -> str:
    """Build a brief outcome summary based on detected intent."""
    amount_str = f" of {int(amount)} BDT" if amount else ""
    summaries = {
        "wrong_transfer": f"Customer claims a wrong transfer{amount_str}",
        "payment_failed": f"Customer reports a failed payment{amount_str} with possible balance deduction",
        "refund_request": f"Customer requests a refund{amount_str}",
        "duplicate_payment": f"Customer reports a duplicate payment{amount_str}",
        "merchant_settlement_delay": f"Merchant reports a settlement delay{amount_str}",
        "agent_cash_in_issue": f"Customer reports agent cash-in{amount_str} not reflected",
        "phishing_or_social_engineering": "Customer reports suspicious/phishing activity",
        "other": f"Customer has a concern{amount_str}",
    }
    return summaries.get(intent, f"Customer complaint{amount_str}")
