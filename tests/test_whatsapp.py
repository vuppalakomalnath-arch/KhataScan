"""Unit tests for whatsapp.py."""

import pytest
from schemas import CustomerBalance
from whatsapp import (
    build_summary,
    sanitize_template_var,
    wa_link,
)


def test_sanitize_template_var_whitespace_and_newlines():
    raw = "Line 1\nLine 2\r\nLine 3\tTabbed    FourSpaces"
    sanitized = sanitize_template_var(raw)

    # Must contain no newlines, carriage returns, or tabs
    assert "\n" not in sanitized
    assert "\r" not in sanitized
    assert "\t" not in sanitized
    assert "    " not in sanitized
    assert sanitized == "Line 1 Line 2 Line 3 Tabbed FourSpaces"


def test_sanitize_template_var_length_limit():
    long_text = "A" * 2000
    sanitized = sanitize_template_var(long_text, limit=100)
    assert len(sanitized) == 100
    assert sanitized.endswith("…")


def test_build_summary_single_line_and_amounts():
    today = "2026-10-02"
    balances = [
        CustomerBalance(customer_id="1", name="Ramesh Kumar", balance_paise=320000, days_since_payment=14),
        CustomerBalance(customer_id="2", name="Suresh Raina", balance_paise=150000, days_since_payment=3),
        CustomerBalance(customer_id="3", name="Mahesh Babu", balance_paise=-50000, days_since_payment=0),  # advance paid, omitted
    ]

    summary = build_summary("Kiran Store", balances, today)

    # Must be a single line
    assert "\n" not in summary
    assert " | " in summary
    # Total due = 3200 + 1500 = 4700 across 2 customers with positive dues
    assert "Total due ₹4,700.00 across 2 customers" in summary
    assert "1) Ramesh Kumar ₹3,200.00 (14d since payment)" in summary
    assert "2) Suresh Raina ₹1,500.00 (3d since payment)" in summary
    # Mahesh has negative balance so shouldn't be listed as debtor
    assert "Mahesh Babu" not in summary


def test_wa_link_generation():
    text = "Hello Ramesh, payment reminder"

    # 10 digits gets prepended with default 91
    link1 = wa_link("9876543210", text)
    assert link1.startswith("https://wa.me/919876543210?text=")
    assert "Hello%20Ramesh" in link1

    # International formatted string with symbols
    link2 = wa_link("+91 98765-43210", text)
    assert link2.startswith("https://wa.me/919876543210?text=")

    # Custom country code
    link3 = wa_link("4155238886", text, default_cc="1")
    assert link3.startswith("https://wa.me/14155238886?text=")

    # Invalid phone numbers
    assert wa_link("", text) is None
    assert wa_link(None, text) is None
    assert wa_link("123", text) is None
    assert wa_link("notaphonenumber", text) is None
