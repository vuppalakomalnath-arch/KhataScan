"""Unit tests for auth.py."""

import pytest
from auth import (
    hash_pin,
    verify_pin,
    validate_pin_format,
    normalize_whatsapp,
)


def test_hash_and_verify_pin():
    pin = "1234"
    hash_hex, salt_hex = hash_pin(pin)
    assert isinstance(hash_hex, str)
    assert isinstance(salt_hex, str)
    assert len(salt_hex) == 32  # 16 bytes in hex

    # Correct PIN verifies
    assert verify_pin(pin, hash_hex, salt_hex) is True

    # Wrong PIN fails
    assert verify_pin("9999", hash_hex, salt_hex) is False
    assert verify_pin("12345", hash_hex, salt_hex) is False
    assert verify_pin("", hash_hex, salt_hex) is False


def test_pin_format_validation():
    # Valid: 4 to 8 digits
    assert validate_pin_format("1234") is True
    assert validate_pin_format("12345678") is True
    assert validate_pin_format("0000") is True

    # Invalid: non-digit, too short, too long
    assert validate_pin_format("123") is False
    assert validate_pin_format("123456789") is False
    assert validate_pin_format("123a") is False
    assert validate_pin_format("") is False
    assert validate_pin_format(None) is False


def test_normalize_whatsapp():
    # 10-digit Indian numbers
    assert normalize_whatsapp("9876543210") == "+919876543210"
    assert normalize_whatsapp("98765 43210") == "+919876543210"
    assert normalize_whatsapp("98765-43210") == "+919876543210"

    # Already formatted E.164
    assert normalize_whatsapp("+919876543210") == "+919876543210"
    assert normalize_whatsapp("+14155238886") == "+14155238886"

    # Custom default country code
    assert normalize_whatsapp("4155238886", default_cc="1") == "+14155238886"

    # Invalid cases
    assert normalize_whatsapp("") is None
    assert normalize_whatsapp(None) is None
    assert normalize_whatsapp("12345") is None
    assert normalize_whatsapp("abcdefghij") is None
