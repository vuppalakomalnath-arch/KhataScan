"""Authentication, PIN hashing, and phone normalization for KhataScan."""

import hashlib
import hmac
import os
import re
import time
from typing import Optional, Tuple
import streamlit as st

from config import LOGIN_LOCKOUT_SECONDS, LOGIN_MAX_ATTEMPTS


def hash_pin(pin: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """Hash PIN using PBKDF2-HMAC-SHA256 with 200,000 iterations.

    Returns:
        (hash_hex, salt_hex)
    """
    if salt is None:
        salt = os.urandom(16)
    pin_bytes = pin.encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", pin_bytes, salt, 200_000)
    return derived.hex(), salt.hex()


def verify_pin(pin: str, hash_hex: str, salt_hex: str) -> bool:
    """Verify input PIN against stored salt and hash using constant-time comparison."""
    try:
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        pin_bytes = pin.encode("utf-8")
        computed = hashlib.pbkdf2_hmac("sha256", pin_bytes, salt, 200_000)
        return hmac.compare_digest(computed, expected_hash)
    except Exception:
        return False


def validate_pin_format(pin: str) -> bool:
    """PIN must be 4 to 8 digits."""
    return bool(pin and pin.isdigit() and 4 <= len(pin) <= 8)


def normalize_whatsapp(raw: Optional[str], default_cc: str = "91") -> Optional[str]:
    r"""Normalize raw WhatsApp phone input into E.164 format.

    - Strips whitespace, dashes, parentheses.
    - If 10 digits without leading '+', prepends default country code.
    - Must match ^\+\d{10,15}$
    """
    if not raw:
        return None

    cleaned = re.sub(r"[\s\-\(\)]", "", raw.strip())
    if not cleaned:
        return None

    if not cleaned.startswith("+"):
        if re.fullmatch(r"\d{10}", cleaned):
            cleaned = f"+{default_cc}{cleaned}"
        elif re.fullmatch(r"\d{11,15}", cleaned):
            cleaned = f"+{cleaned}"
        else:
            return None

    if re.fullmatch(r"^\+\d{10,15}$", cleaned):
        return cleaned

    return None


def is_locked_out() -> Tuple[bool, int]:
    """Check if the session is locked out due to excessive failed attempts.

    Returns:
        (locked, seconds_remaining)
    """
    locked_until = st.session_state.get("locked_until", 0)
    now = time.time()
    if now < locked_until:
        return True, int(locked_until - now)
    return False, 0


def record_failed_login() -> int:
    """Record a failed login attempt and trigger lockout if limit reached."""
    attempts = st.session_state.get("login_attempts", 0) + 1
    st.session_state["login_attempts"] = attempts
    if attempts >= LOGIN_MAX_ATTEMPTS:
        st.session_state["locked_until"] = time.time() + LOGIN_LOCKOUT_SECONDS
    return attempts


def reset_login_attempts() -> None:
    """Reset failed login attempts upon successful login."""
    st.session_state["login_attempts"] = 0
    st.session_state["locked_until"] = 0
