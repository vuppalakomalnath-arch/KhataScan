"""Unit tests for ledger validation, deduplication, balances, and aging."""

import pytest
from schemas import ExtractedEntry, ExtractedPage
from ledger import (
    compute_balances,
    dedupe_key,
    validate_page,
)


def test_validation_flags():
    today = "2026-10-02"
    entries = [
        # Clean row
        ExtractedEntry(row_number=1, date="2026-10-01", customer_name_raw="Ramesh", amount=500.0, entry_type="credit", confidence=0.95),
        # low_confidence
        ExtractedEntry(row_number=2, date="2026-10-01", customer_name_raw="Suresh", amount=200.0, entry_type="credit", confidence=0.60),
        # missing_amount & unknown_type
        ExtractedEntry(row_number=3, date="2026-10-01", customer_name_raw="Mahesh", amount=None, entry_type="unknown", confidence=0.90),
        # non_positive_amount
        ExtractedEntry(row_number=4, date="2026-10-01", customer_name_raw="Naresh", amount=-50.0, entry_type="credit", confidence=0.90),
        # amount_outlier (> 50,000)
        ExtractedEntry(row_number=5, date="2026-10-01", customer_name_raw="Dinesh", amount=75000.0, entry_type="credit", confidence=0.90),
        # missing_date
        ExtractedEntry(row_number=6, date=None, date_raw=None, customer_name_raw="Ganesh", amount=100.0, entry_type="credit", confidence=0.90),
        # future_date
        ExtractedEntry(row_number=7, date="2026-10-15", customer_name_raw="Mukesh", amount=100.0, entry_type="credit", confidence=0.90),
        # missing_name
        ExtractedEntry(row_number=8, date="2026-10-01", customer_name_raw=None, customer_name_latin=None, amount=100.0, entry_type="credit", confidence=0.90),
    ]

    page = ExtractedPage(is_ledger_page=True, image_quality="good", entries=entries)
    validated, total_mismatch = validate_page(page, today)

    assert len(validated) == 8
    assert validated[0]["flags"] == []
    assert "low_confidence" in validated[1]["flags"]
    assert "missing_amount" in validated[2]["flags"]
    assert "unknown_type" in validated[2]["flags"]
    assert "non_positive_amount" in validated[3]["flags"]
    assert "amount_outlier" in validated[4]["flags"]
    assert "missing_date" in validated[5]["flags"]
    assert "future_date" in validated[6]["flags"]
    assert "missing_name" in validated[7]["flags"]
    assert total_mismatch is False


def test_total_mismatch_flag():
    today = "2026-10-02"
    entries = [
        ExtractedEntry(row_number=1, date="2026-10-01", customer_name_raw="Ramesh", amount=500.0, entry_type="credit", confidence=0.95),
        ExtractedEntry(row_number=2, date="2026-10-01", customer_name_raw="Suresh", amount=300.0, entry_type="credit", confidence=0.95),
    ]
    # Stated page total says 1000.0 but actual credit sum is 800.0
    page = ExtractedPage(is_ledger_page=True, image_quality="good", stated_page_total=1000.0, entries=entries)
    _, total_mismatch = validate_page(page, today)
    assert total_mismatch is True

    # Matching total
    page_matching = ExtractedPage(is_ledger_page=True, image_quality="good", stated_page_total=800.0, entries=entries)
    _, total_mismatch2 = validate_page(page_matching, today)
    assert total_mismatch2 is False


def test_dedupe_key_stability():
    # Dedupe key should be stable regardless of whitespace and casing
    k1 = dedupe_key("ramesh kumar", "2026-10-01", 50000, "credit", "milk & bread")
    k2 = dedupe_key("  Ramesh Kumar ", "2026-10-01", 50000, "CREDIT", " Milk & Bread ")
    assert k1 == k2


def test_compute_balances_and_aging():
    today = "2026-10-15"
    customers = [
        {"_id": "cust_1", "display_name": "Ramesh Kumar"},
        {"_id": "cust_2", "display_name": "Suresh Raina"},
    ]
    entries = [
        # Ramesh: credit 500 (50000 paise) + payment 200 (20000 paise) -> 300 due (30000 paise)
        {"customer_id": "cust_1", "entry_date": "2026-10-01", "entry_type": "credit", "amount_paise": 50000},
        {"customer_id": "cust_1", "entry_date": "2026-10-05", "entry_type": "payment", "amount_paise": 20000},
        # Suresh: overpayment -> credit 100 + payment 150 -> balance -50
        {"customer_id": "cust_2", "entry_date": "2026-10-02", "entry_type": "credit", "amount_paise": 10000},
        {"customer_id": "cust_2", "entry_date": "2026-10-10", "entry_type": "payment", "amount_paise": 15000},
    ]

    balances = compute_balances(entries, customers, today)
    assert len(balances) == 2

    ramesh = next(b for b in balances if b.customer_id == "cust_1")
    assert ramesh.balance_paise == 30000
    assert ramesh.last_activity == "2026-10-05"
    assert ramesh.last_payment_date == "2026-10-05"
    # Days from 2026-10-05 to 2026-10-15 = 10 days
    assert ramesh.days_since_payment == 10

    suresh = next(b for b in balances if b.customer_id == "cust_2")
    assert suresh.balance_paise == -5000  # negative for overpayment
    assert suresh.days_since_payment == 5


def test_aging_without_payments():
    today = "2026-10-10"
    customers = [{"_id": "cust_3", "display_name": "New Customer"}]
    entries = [
        {"customer_id": "cust_3", "entry_date": "2026-10-01", "entry_type": "credit", "amount_paise": 25000}
    ]
    balances = compute_balances(entries, customers, today)
    cust = balances[0]
    # Days since earliest credit = 9 days
    assert cust.days_since_payment == 9
    assert cust.last_payment_date is None
