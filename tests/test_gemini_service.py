"""Unit tests for prompts, schema parsing, and gemini service logic."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from prompts import (
    EXTRACTION_PROMPT,
    PROMPT_VERSION,
    REMINDER_FALLBACK_TEMPLATE,
    REMINDER_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)
from schemas import ExtractedPage
from gemini_service import draft_reminder


def test_prompts_integrity():
    assert PROMPT_VERSION == "v1"
    assert "{today}" in EXTRACTION_PROMPT
    assert "{shop_name}" in SYSTEM_PROMPT
    assert "LEDGER_CONTEXT" in SYSTEM_PROMPT
    assert "{amount_text}" in REMINDER_PROMPT
    assert "{customer_name}" in REMINDER_FALLBACK_TEMPLATE


def test_fixture_sample_extraction():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_extraction.json"
    assert fixture_path.exists()
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    # Validates into ExtractedPage schema
    page = ExtractedPage.model_validate(data)
    assert page.is_ledger_page is True
    assert len(page.entries) == 2
    assert page.entries[0].amount == 1250.0
    assert page.entries[0].entry_type == "credit"
    assert page.entries[1].entry_type == "payment"


def test_draft_reminder_guard_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = (
        "Dear Ramesh Kumar, this is a friendly reminder from Kiran Store that ₹1,250.00 "
        "is pending on your account. Kindly clear it soon. - Kiran Store"
    )
    mock_client.models.generate_content.return_value = mock_response

    facts = {
        "shop_name": "Kiran Store",
        "customer_name": "Ramesh Kumar",
        "amount_text": "₹1,250.00",
        "days_text": "14 days",
    }
    result = draft_reminder(mock_client, facts)
    assert "₹1,250.00" in result
    assert "Ramesh Kumar" in result


def test_draft_reminder_guard_triggers_fallback_on_missing_amount():
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Hallucinated different amount or omitted it
    mock_response.text = "Hello Ramesh, please pay your dues. Thanks, Kiran Store"
    mock_client.models.generate_content.return_value = mock_response

    facts = {
        "shop_name": "Kiran Store",
        "customer_name": "Ramesh Kumar",
        "amount_text": "₹1,250.00",
        "days_text": "14 days",
    }
    result = draft_reminder(mock_client, facts)
    # Should fall back to deterministic template containing exact amount
    assert "₹1,250.00" in result
    assert "gentle reminder" in result


def test_draft_reminder_guard_triggers_fallback_on_other_customer_name():
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Hallucinated another customer's name
    mock_response.text = "Dear Ramesh Kumar and Suresh Raina, ₹1,250.00 is due."
    mock_client.models.generate_content.return_value = mock_response

    facts = {
        "shop_name": "Kiran Store",
        "customer_name": "Ramesh Kumar",
        "amount_text": "₹1,250.00",
        "days_text": "14 days",
    }
    result = draft_reminder(mock_client, facts, other_customers=["Suresh Raina", "Mohan Lal"])
    # Fallback template used because another customer name was mentioned
    assert result == REMINDER_FALLBACK_TEMPLATE.format(
        customer_name="Ramesh Kumar",
        shop_name="Kiran Store",
        amount_text="₹1,250.00",
    )
