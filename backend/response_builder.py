"""
Response builder — generates agent_summary, recommended_next_action, and customer_reply.

Uses template-based generation with dynamic slots for transaction IDs, amounts, etc.
Supports Bangla replies when the detected language is "bn".
"""

from __future__ import annotations

from typing import Any, Optional


# ─── Bangla customer reply templates ──────────────────────────────────────────

_BANGLA_TEMPLATES: dict[str, str] = {
    "wrong_transfer": (
        "আপনার লেনদেন {txn_ref}এর বিষয়ে আমরা অবগত হয়েছি। "
        "আমাদের বিরোধ নিষ্পত্তি দল এটি দ্রুত যাচাই করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
    "payment_failed": (
        "আপনার লেনদেন {txn_ref}এ সমস্যা হয়ে থাকতে পারে। "
        "আমাদের পেমেন্ট দল বিষয়টি যাচাই করবে এবং যোগ্য কোনো পরিমাণ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
    "refund_request": (
        "আপনার অনুরোধ আমরা পেয়েছি। সম্পন্ন লেনদেনের রিফান্ড মার্চেন্টের নিজস্ব নীতির উপর নির্ভর করে। "
        "মার্চেন্টের সাথে সরাসরি যোগাযোগ করার পরামর্শ দেওয়া হচ্ছে। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
    "duplicate_payment": (
        "আপনার লেনদেন {txn_ref}এ সম্ভাব্য ডুপ্লিকেট পেমেন্ট লক্ষ্য করা গেছে। "
        "আমাদের পেমেন্ট দল বিলারের সাথে যাচাই করবে এবং যোগ্য কোনো পরিমাণ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
    "merchant_settlement_delay": (
        "আপনার সেটেলমেন্ট {txn_ref}এর বিষয়ে আমরা অবগত হয়েছি। "
        "আমাদের মার্চেন্ট অপারেশন্স দল ব্যাচের স্ট্যাটাস যাচাই করে আপনাকে অফিসিয়াল চ্যানেলে জানাবে।"
    ),
    "agent_cash_in_issue": (
        "আপনার লেনদেন {txn_ref}এর বিষয়ে আমরা অবগত হয়েছি। "
        "আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
    "phishing_or_social_engineering": (
        "তথ্য শেয়ার করার আগে আমাদের সাথে যোগাযোগ করার জন্য ধন্যবাদ। "
        "আমরা কখনই আপনার পিন, ওটিপি, বা পাসওয়ার্ড জিজ্ঞাসা করি না — কোনো পরিস্থিতিতেই নয়। "
        "অনুগ্রহ করে এগুলো কারো সাথে শেয়ার করবেন না, এমনকি যদি তারা আমাদের পক্ষ থেকে দাবি করে। "
        "আমাদের জালিয়াতি দলকে এই ঘটনার বিষয়ে জানানো হয়েছে।"
    ),
    "other": (
        "আমাদের সাথে যোগাযোগ করার জন্য ধন্যবাদ। আপনাকে দ্রুত সাহায্য করতে, অনুগ্রহ করে লেনদেন আইডি, "
        "জড়িত পরিমাণ, এবং কী সমস্যা হয়েছে তার সংক্ষিপ্ত বিবরণ শেয়ার করুন। "
        "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
}


# ─── English customer reply templates ────────────────────────────────────────

_ENGLISH_TEMPLATES: dict[str, str] = {
    "wrong_transfer": (
        "We have noted your concern about transaction {txn_ref}. "
        "Please do not share your PIN or OTP with anyone. "
        "Our dispute team will review the case and contact you through official support channels."
    ),
    "payment_failed": (
        "We have noted that transaction {txn_ref} may have caused an unexpected balance deduction. "
        "Our payments team will review the case and any eligible amount will be returned through official channels. "
        "Please do not share your PIN or OTP with anyone."
    ),
    "refund_request": (
        "Thank you for reaching out. Refunds for completed merchant payments depend on the merchant's own policy. "
        "We recommend contacting the merchant directly. If you need help reaching them, please reply and we will guide you. "
        "Please do not share your PIN or OTP with anyone."
    ),
    "duplicate_payment": (
        "We have noted the possible duplicate payment for transaction {txn_ref}. "
        "Our payments team will verify with the biller and any eligible amount will be returned through official channels. "
        "Please do not share your PIN or OTP with anyone."
    ),
    "merchant_settlement_delay": (
        "We have noted your concern about settlement {txn_ref}. "
        "Our merchant operations team will check the batch status and update you on the expected settlement time through official channels."
    ),
    "agent_cash_in_issue": (
        "We have noted your concern about transaction {txn_ref}. "
        "Our agent operations team will investigate and update you through official support channels. "
        "Please do not share your PIN or OTP with anyone."
    ),
    "phishing_or_social_engineering": (
        "Thank you for reaching out before sharing any information. "
        "We never ask for your PIN, OTP, or password under any circumstances. "
        "Please do not share these with anyone, even if they claim to be from us. "
        "Our fraud team has been notified of this incident."
    ),
    "other": (
        "Thank you for reaching out. To help you faster, please share the transaction ID, "
        "the amount involved, and a short description of what went wrong. "
        "Please do not share your PIN or OTP with anyone."
    ),
    "insufficient_clarification": (
        "Thank you for reaching out. To help you faster, please share the transaction ID, "
        "the amount involved, and a short description of what went wrong. "
        "Please do not share your PIN or OTP with anyone."
    ),
}

# ─── Agent summary templates ─────────────────────────────────────────────────

_AGENT_SUMMARY_TEMPLATES: dict[str, str] = {
    "wrong_transfer": (
        "Customer reports sending {amount_str} via {txn_id} to {counterparty}, "
        "which they now believe was the wrong recipient.{inconsistency_note}"
    ),
    "payment_failed": (
        "Customer attempted a {amount_str} {payment_desc} ({txn_id}) which {status_desc}. "
        "Reports balance was deducted. Requires payments operations investigation."
    ),
    "refund_request": (
        "Customer requests refund of {amount_str} for {txn_id} ({payment_desc}). "
        "{refund_reason}"
    ),
    "duplicate_payment": (
        "Customer reports duplicate {payment_desc}. {duplicate_detail}"
    ),
    "merchant_settlement_delay": (
        "Merchant reports {amount_str} settlement ({txn_id}) is delayed beyond the standard window. "
        "Settlement status is {status}."
    ),
    "agent_cash_in_issue": (
        "Customer reports {amount_str} cash-in via {counterparty} ({txn_id}) not reflected in balance. "
        "Transaction status is {status}.{agent_note}"
    ),
    "phishing_or_social_engineering": (
        "Customer reports an unsolicited communication claiming to be from the company. "
        "{phishing_detail} Likely social engineering attempt."
    ),
    "other": (
        "Customer reports a concern. {vague_detail}"
    ),
}


# ─── Recommended next action templates ────────────────────────────────────────

_NEXT_ACTION_TEMPLATES: dict[str, str] = {
    "wrong_transfer": (
        "Verify {txn_id} details with the customer and initiate the wrong-transfer dispute workflow per policy."
    ),
    "wrong_transfer_inconsistent": (
        "Flag for human review. Verify with the customer whether this was genuinely a wrong transfer "
        "given the established transaction pattern with this recipient."
    ),
    "payment_failed": (
        "Investigate {txn_id} ledger status. If balance was deducted on a failed payment, "
        "initiate the automatic reversal flow within standard SLA."
    ),
    "refund_request": (
        "Inform the customer that refund eligibility depends on the merchant's own policy. "
        "Provide guidance on contacting the merchant directly for a refund."
    ),
    "duplicate_payment": (
        "Verify the duplicate with payments_ops. If the biller confirms only one payment was received, "
        "initiate reversal of {txn_id}."
    ),
    "merchant_settlement_delay": (
        "Route to merchant_operations to verify settlement batch status. "
        "If the batch is delayed, communicate a revised ETA to the merchant."
    ),
    "agent_cash_in_issue": (
        "Investigate {txn_id} pending status with agent operations. "
        "Confirm settlement state and resolve within the standard cash-in SLA."
    ),
    "phishing_or_social_engineering": (
        "Escalate to fraud_risk team immediately. Confirm to customer that the company never asks for OTP. "
        "Log the reported details for fraud pattern analysis."
    ),
    "other": (
        "Reply to customer asking for specific details: which transaction, what amount, "
        "what went wrong, and approximate time."
    ),
    "ambiguous": (
        "Reply to customer asking for additional details to identify the correct transaction. "
        "Do not initiate dispute until the transaction is confirmed."
    ),
}


# ─── Public API ───────────────────────────────────────────────────────────────

def build_response_fields(
    extracted: dict[str, Any],
    case_type: str,
    evidence_verdict: str,
    matched_txn: Optional[dict[str, Any]],
    all_transactions: list[dict[str, Any]] | None,
    reason_codes: list[str],
) -> dict[str, str]:
    """
    Build agent_summary, recommended_next_action, and customer_reply.

    Returns a dict with these three string fields.
    """
    language = extracted.get("language_detected", "en")
    txn_id = matched_txn.get("transaction_id", "unknown") if matched_txn else None
    amount = matched_txn.get("amount") if matched_txn else extracted.get("claimed_amount")
    counterparty = matched_txn.get("counterparty", "unknown") if matched_txn else extracted.get("claimed_counterparty", "unknown")
    status = matched_txn.get("status", "unknown") if matched_txn else "unknown"

    amount_str = f"{int(amount)} BDT" if amount else "an unspecified amount"
    txn_ref = txn_id if txn_id else "your ticket"

    # ── Agent summary ──
    agent_summary = _build_agent_summary(
        case_type, evidence_verdict, txn_id, amount_str,
        counterparty, status, matched_txn, all_transactions, extracted
    )

    # ── Recommended next action ──
    next_action = _build_next_action(
        case_type, evidence_verdict, txn_id, reason_codes
    )

    # ── Customer reply ──
    customer_reply = _build_customer_reply(
        case_type, evidence_verdict, txn_ref, language, reason_codes
    )

    return {
        "agent_summary": agent_summary,
        "recommended_next_action": next_action,
        "customer_reply": customer_reply,
    }


# ─── Internal builders ───────────────────────────────────────────────────────

def _build_agent_summary(
    case_type: str,
    verdict: str,
    txn_id: Optional[str],
    amount_str: str,
    counterparty: str,
    status: str,
    matched_txn: Optional[dict],
    all_transactions: list[dict] | None,
    extracted: dict[str, Any],
) -> str:
    """Build a factual, agent-facing summary."""

    if case_type == "wrong_transfer":
        inconsistency_note = ""
        if verdict == "inconsistent" and all_transactions:
            prior = sum(
                1 for t in all_transactions
                if t.get("counterparty") == counterparty
                and t.get("transaction_id") != txn_id
            )
            if prior >= 2:
                inconsistency_note = (
                    f" However, transaction history shows {prior} prior transfers to the same "
                    f"counterparty, suggesting an established recipient."
                )
            elif prior == 1:
                inconsistency_note = (
                    " However, transaction history shows a prior transfer to the same "
                    "counterparty."
                )
        if txn_id:
            return f"Customer reports sending {amount_str} via {txn_id} to {counterparty}, which they now believe was the wrong recipient.{inconsistency_note}"
        return f"Customer claims a wrong transfer of {amount_str}.{inconsistency_note} Insufficient data to identify the specific transaction."

    if case_type == "payment_failed":
        status_desc = "failed" if status == "failed" else f"shows status '{status}'"
        payment_desc = "payment"
        if matched_txn:
            cp = matched_txn.get("counterparty", "")
            if cp.startswith("MERCHANT"):
                payment_desc = "merchant payment"
            elif cp.startswith("BILLER"):
                payment_desc = f"payment to {cp}"
            else:
                payment_desc = "payment"
        if txn_id:
            return f"Customer attempted a {amount_str} {payment_desc} ({txn_id}) which {status_desc}, but reports balance was deducted. Requires payments operations investigation."
        return f"Customer reports a failed payment of {amount_str} with balance deduction."

    if case_type == "refund_request":
        if txn_id:
            return f"Customer requests refund of {amount_str} for {txn_id} (merchant payment) due to change of mind. Not a service failure."
        return f"Customer requests refund of {amount_str}."

    if case_type == "duplicate_payment":
        if all_transactions:
            claimed_amount = extracted.get("claimed_amount")
            dupes = [t for t in all_transactions if t.get("amount") == claimed_amount and t.get("type") == "payment"]
            if len(dupes) >= 2:
                ids = [t.get("transaction_id", "?") for t in dupes]
                try:
                    ts = [t.get("timestamp", "") for t in dupes]
                    from datetime import datetime as dt
                    parsed = sorted(dt.fromisoformat(t.replace("Z", "+00:00")) for t in ts)
                    diff = (parsed[-1] - parsed[0]).total_seconds()
                    return (
                        f"Customer reports duplicate payment. "
                        f"Two identical {amount_str} payments were completed {int(diff)} seconds apart "
                        f"({' and '.join(ids)}). The second is likely the duplicate."
                    )
                except (ValueError, IndexError):
                    return f"Customer reports duplicate payment of {amount_str}. Transactions: {', '.join(ids)}."
        if txn_id:
            return f"Customer reports duplicate payment of {amount_str} ({txn_id})."
        return f"Customer reports duplicate payment of {amount_str}."

    if case_type == "merchant_settlement_delay":
        if txn_id:
            return f"Merchant reports {amount_str} settlement ({txn_id}) is delayed beyond the standard window. Settlement status is {status}."
        return f"Merchant reports settlement delay of {amount_str}."

    if case_type == "agent_cash_in_issue":
        agent_note = ""
        if "agent" in (extracted.get("claimed_outcome") or "").lower() or counterparty.startswith("AGENT"):
            agent_note = " Agent claims funds were sent."
        if txn_id:
            return f"Customer reports {amount_str} cash-in via {counterparty} ({txn_id}) not reflected in balance. Transaction status is {status}.{agent_note}"
        return f"Customer reports agent cash-in of {amount_str} not reflected in balance."

    if case_type == "phishing_or_social_engineering":
        return (
            "Customer reports an unsolicited call/message claiming to be from the company "
            "and asking for credentials. Likely social engineering attempt."
        )

    # "other" or vague
    if verdict == "insufficient_data":
        return "Customer reports a vague concern without specifying transaction, amount, or issue. Insufficient detail to identify any relevant transaction."
    return "Customer reports a concern. Insufficient detail for automatic classification."


def _build_next_action(
    case_type: str,
    verdict: str,
    txn_id: Optional[str],
    reason_codes: list[str],
) -> str:
    """Build operational next-step instruction for the agent."""
    txn_ref = txn_id or "the transaction"

    if "ambiguous_match" in reason_codes or "needs_clarification" in reason_codes:
        if case_type == "wrong_transfer":
            return "Reply to customer asking for the recipient's number to identify the correct transaction. Do not initiate dispute until the transaction is confirmed."
        return _NEXT_ACTION_TEMPLATES.get("ambiguous", "").format(txn_id=txn_ref)

    if case_type == "wrong_transfer" and verdict == "inconsistent":
        return _NEXT_ACTION_TEMPLATES["wrong_transfer_inconsistent"]

    template_key = case_type
    template = _NEXT_ACTION_TEMPLATES.get(template_key, _NEXT_ACTION_TEMPLATES["other"])
    return template.format(txn_id=txn_ref)


def _build_customer_reply(
    case_type: str,
    verdict: str,
    txn_ref: str,
    language: str,
    reason_codes: list[str],
) -> str:
    """Build a safe, professional customer-facing reply."""
    # If clarification needed, use a clarification template
    if "needs_clarification" in reason_codes or "ambiguous_match" in reason_codes:
        if case_type == "wrong_transfer":
            if language == "bn":
                return (
                    "আমাদের সাথে যোগাযোগ করার জন্য ধন্যবাদ। ঐ তারিখে একাধিক লেনদেন দেখা যাচ্ছে। "
                    "সঠিক লেনদেন চিহ্নিত করতে অনুগ্রহ করে প্রাপকের নম্বরটি শেয়ার করুন। "
                    "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
                )
            return (
                f"Thank you for reaching out. We see multiple transactions that could match your concern. "
                f"Could you share the recipient's number so we can identify the right transaction? "
                f"Please do not share your PIN or OTP with anyone."
            )
        templates = _BANGLA_TEMPLATES if language == "bn" else _ENGLISH_TEMPLATES
        return templates.get("other", templates["other"]).format(txn_ref=txn_ref)

    # Select language-appropriate template
    templates = _BANGLA_TEMPLATES if language == "bn" else _ENGLISH_TEMPLATES
    template = templates.get(case_type, templates["other"])
    return template.format(txn_ref=txn_ref)
