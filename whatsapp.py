"""Twilio WhatsApp dispatch, Content Template variable sanitization, and wa.me links.

Source of Truth: spec.md §8.5
Principle: Summary numbers are computed by deterministic code, NEVER by LLM.
"""

import json
import re
import urllib.parse
from typing import Any, List, Optional, Tuple
import streamlit as st
from twilio.rest import Client

from config import DEFAULT_COUNTRY_CODE, WHATSAPP_VAR_LIMIT, get_secret
from schemas import CustomerBalance, format_inr


def sanitize_template_var(text: str, limit: int = WHATSAPP_VAR_LIMIT) -> str:
    """Sanitize variable for WhatsApp Content Template.

    WhatsApp template variable rules:
    - No newlines, carriage returns, or tabs.
    - No consecutive spaces (4 or more).
    - Truncate with ellipsis if exceeding character limit.
    """
    if not text:
        return ""

    # Replace newlines, tabs, and multi-whitespace runs with a single space
    sanitized = re.sub(r"[\r\n\t]+", " ", text)
    sanitized = re.sub(r" {2,}", " ", sanitized).strip()

    if len(sanitized) > limit:
        sanitized = sanitized[: limit - 1] + "…"

    return sanitized


def build_summary(
    shop_name: str,
    balances: List[CustomerBalance],
    today: str,
) -> str:
    """Build single-line WhatsApp dues summary for top 10 customers.

    Example:
    Total due ₹12,500.00 across 6 customers | 1) Ramesh Kumar ₹3,200.00 (14d since payment) | 2) ...
    """
    debtors = [b for b in balances if b.balance_paise > 0]
    total_due_paise = sum(b.balance_paise for b in debtors)
    count = len(debtors)

    parts = [
        f"Total due {format_inr(total_due_paise)} across {count} customer{'s' if count != 1 else ''}"
    ]

    for idx, b in enumerate(debtors[:10], start=1):
        aging_text = (
            f"{b.days_since_payment}d since payment"
            if b.days_since_payment is not None
            else "no payment recorded"
        )
        parts.append(f"{idx}) {b.name} {format_inr(b.balance_paise)} ({aging_text})")

    summary_raw = " | ".join(parts)
    return sanitize_template_var(summary_raw)


@st.cache_resource
def get_twilio_client() -> Optional[Client]:
    """Obtain cached Twilio client from credentials."""
    account_sid = get_secret("TWILIO_ACCOUNT_SID")
    auth_token = get_secret("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return None
    return Client(account_sid, auth_token)


def send_whatsapp(
    client: Optional[Client],
    from_: str,
    to_number: str,
    user_name: str,
    summary: str,
    content_sid: Optional[str] = None,
) -> Tuple[bool, str]:
    """Dispatch WhatsApp message using Twilio Content Template (or fallback body).

    Returns:
        (ok: bool, info: str)
    """
    if not client:
        return False, "Twilio credentials (ACCOUNT_SID / AUTH_TOKEN) not configured."

    # Format destination number to E.164 without leading spaces or dashes
    cleaned_to = re.sub(r"[^\d\+]", "", to_number)
    if not cleaned_to.startswith("+"):
        cleaned_to = f"+{cleaned_to}"

    to_addr = f"whatsapp:{cleaned_to}"
    from_addr = from_ if from_.startswith("whatsapp:") else f"whatsapp:{from_}"
    var_2 = sanitize_template_var(summary)

    try:
        if content_sid:
            content_vars = json.dumps({"1": user_name, "2": var_2}, ensure_ascii=False)
            msg = client.messages.create(
                from_=from_addr,
                to=to_addr,
                content_sid=content_sid,
                content_variables=content_vars,
            )
            return True, str(msg.sid)
        else:
            # Fallback plain message if Content Template SID is not yet approved/configured
            body_text = f"Hi {user_name}, here's your KhataScan summary:\n\n{summary}"
            msg = client.messages.create(
                from_=from_addr,
                to=to_addr,
                body=body_text,
            )
            return True, str(msg.sid)
    except Exception as e:
        return False, str(e)


def wa_link(
    phone: Optional[str],
    text: str,
    default_cc: str = DEFAULT_COUNTRY_CODE,
) -> Optional[str]:
    """Generate wa.me direct link for customer payment reminders.

    Digits only in international format without '+' or special symbols.
    """
    if not phone:
        return None

    digits = re.sub(r"\D", "", phone.strip())
    if not digits:
        return None

    # If standard 10-digit number without country code
    if len(digits) == 10:
        digits = f"{default_cc}{digits}"
    elif len(digits) < 10 or len(digits) > 15:
        return None

    encoded_text = urllib.parse.quote(text)
    return f"https://wa.me/{digits}?text={encoded_text}"
