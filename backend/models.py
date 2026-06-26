"""
Pydantic models for QueueStorm Investigator API.
Every enum field uses Literal types — invalid values become validation errors,
not silent schema violations.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enum Literal types ──────────────────────────────────────────────────────

LanguageType = Literal["en", "bn", "mixed"]
ChannelType = Literal[
    "in_app_chat", "call_center", "email", "merchant_portal", "field_agent"
]
UserType = Literal["customer", "merchant", "agent", "unknown"]
TransactionType = Literal[
    "transfer", "payment", "cash_in", "cash_out", "settlement", "refund"
]
TransactionStatus = Literal["completed", "failed", "pending", "reversed"]

EvidenceVerdict = Literal["consistent", "inconsistent", "insufficient_data"]
CaseType = Literal[
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
]
Severity = Literal["low", "medium", "high", "critical"]
Department = Literal[
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
]


# ─── Request models ──────────────────────────────────────────────────────────

class TransactionEntry(BaseModel):
    transaction_id: str
    timestamp: str
    type: TransactionType
    amount: float
    counterparty: str
    status: TransactionStatus


class TicketRequest(BaseModel):
    ticket_id: str
    complaint: str
    language: Optional[LanguageType] = None
    channel: Optional[ChannelType] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: Optional[list[TransactionEntry]] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("complaint")
    @classmethod
    def complaint_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("complaint must not be empty")
        return v


# ─── Response model ──────────────────────────────────────────────────────────

class TicketResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str] = None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: Optional[list[str]] = None
