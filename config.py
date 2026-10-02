"""Configuration and secrets access for KhataScan."""

import os
from typing import Any, Optional
import streamlit as st

# Defaults and limits specified in spec.md §5
MODEL_NAME_DEFAULT = "gemini-2.5-flash"  # Verified fast multi-modal flash model
MAX_IMAGE_SIDE_PX = 2000
MIN_IMAGE_SIDE_PX = 600
JPEG_QUALITY = 85
MAX_UPLOAD_MB = 8
CONF_REVIEW_THRESHOLD = 0.85
MATCH_AUTO = 92
MATCH_SUGGEST = 75
MATCH_TIE_MARGIN = 5
AMOUNT_OUTLIER_RUPEES = 50_000
WHATSAPP_VAR_LIMIT = 1500
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300
REMINDER_LANGUAGES = ["English", "Hindi", "Telugu"]
DEFAULT_COUNTRY_CODE = "91"
PROMPT_VERSION = "v1"


def get_secret(name: str, default: Optional[Any] = None) -> Any:
    """Retrieve secret from st.secrets if available, else environment variable.

    This ensures tests and background scripts run without Streamlit context.
    """
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            val = st.secrets[name]
            if val is not None and str(val).strip() != "":
                return val
    except Exception:
        pass

    env_val = os.environ.get(name)
    if env_val is not None and str(env_val).strip() != "":
        return env_val

    return default
