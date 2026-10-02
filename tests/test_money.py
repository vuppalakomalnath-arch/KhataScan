"""Tests for money conversion and formatting helpers."""

import pytest
from schemas import rupees_to_paise, format_inr


def test_rupees_to_paise_standard():
    assert rupees_to_paise(12.5) == 1250
    assert rupees_to_paise(0.0) == 0
    assert rupees_to_paise(100) == 10000
    assert rupees_to_paise(None) == 0


def test_rupees_to_paise_rounding_half_up():
    # 12.505 rounds to 1251 paise
    assert rupees_to_paise(12.505) == 1251
    # 12.504 rounds down to 1250 paise
    assert rupees_to_paise(12.504) == 1250
    # Negative values
    assert rupees_to_paise(-10.5) == -1050


def test_format_inr_examples():
    # §13 explicit requirement: format_inr(125000)="₹1,250.00"
    assert format_inr(125000) == "₹1,250.00"
    assert format_inr(0) == "₹0.00"
    assert format_inr(50) == "₹0.50"
    assert format_inr(100) == "₹1.00"


def test_format_inr_indian_numbering():
    # 1 Lakh Rupees = 10,000,000 paise
    assert format_inr(10000000) == "₹1,00,000.00"
    # 10 Lakh Rupees = 100,000,000 paise
    assert format_inr(100000000) == "₹10,00,000.00"
    # Negative amounts
    assert format_inr(-25050) == "-₹250.50"
