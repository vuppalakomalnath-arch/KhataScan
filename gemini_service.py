"""Gemini API vision extraction, chat factory, and reminder drafting.

Source of Truth: spec.md §8.3
Core Principle: AI reads. Code computes. Human verifies.
"""

import json
import time
from typing import Any, Dict, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError
import streamlit as st

from config import MODEL_NAME_DEFAULT, get_secret
from prompts import (
    EXTRACTION_PROMPT,
    REPAIR_PROMPT,
    REMINDER_FALLBACK_TEMPLATE,
    REMINDER_PROMPT,
    SYSTEM_PROMPT,
)
from schemas import ExtractedPage


class ExtractionError(Exception):
    """Raised when page extraction from Gemini fails or returns unparseable content."""
    pass


def get_model_name() -> str:
    """Return model name configured in secrets or default."""
    return get_secret("MODEL_NAME", MODEL_NAME_DEFAULT)


@st.cache_resource
def get_gemini_client(api_key: Optional[str] = None) -> genai.Client:
    """Obtain cached Gemini client instance per spec.md §8.3 [PDF gotcha]."""
    key = api_key or get_secret("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured in .streamlit/secrets.toml")
    return genai.Client(api_key=key)


def _call_with_retry(fn, max_retries: int = 2, base_delay: float = 2.0):
    """Execute function with exponential backoff on 429/5xx errors."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except APIError as e:
            last_err = e
            code = getattr(e, "code", None)
            if code in (429, 500, 503) and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
        except Exception as e:
            last_err = e
            # Handle rate limit or temporary network blip
            err_str = str(e).lower()
            if ("429" in err_str or "quota" in err_str or "overloaded" in err_str) and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise last_err


def extract_page(
    client: genai.Client,
    image_bytes: bytes,
    today: str,
) -> ExtractedPage:
    """Extract structured ledger rows from image bytes.

    Uses response_mime_type="application/json" and response_schema=ExtractedPage.
    Includes retry logic and one JSON repair attempt on failure.
    """
    model = get_model_name()
    prompt_text = EXTRACTION_PROMPT.format(today=today)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

    config = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=ExtractedPage,
    )

    def _generate():
        return client.models.generate_content(
            model=model,
            contents=[image_part, prompt_text],
            config=config,
        )

    try:
        response = _call_with_retry(_generate)
    except Exception as e:
        raise ExtractionError(f"Gemini API call failed: {e}") from e

    raw_text = response.text or ""
    try:
        # Validate through Pydantic
        return ExtractedPage.model_validate_json(raw_text)
    except Exception as parse_err:
        # Attempt one repair call per spec.md §8.3
        repair_msg = REPAIR_PROMPT.format(
            error=str(parse_err),
            previous_output=raw_text[:2000],
        )

        def _generate_repair():
            return client.models.generate_content(
                model=model,
                contents=[repair_msg],
                config=config,
            )

        try:
            repair_response = _call_with_retry(_generate_repair)
            return ExtractedPage.model_validate_json(repair_response.text or "")
        except Exception as second_err:
            raise ExtractionError(
                f"Ledger extraction failed schema validation: {second_err}"
            ) from second_err


def draft_reminder(
    client: genai.Client,
    facts: Dict[str, Any],
    language: str = "English",
    tone: str = "gentle",
    other_customers: Optional[list] = None,
) -> str:
    """Draft a polite payment reminder with strict code guards per spec.md §8.3.

    Guard:
    1. Must contain facts['amount_text'] exactly.
    2. Must be under 600 characters.
    3. Must not mention other customer names.
    Fallback to deterministic template if guard fails.
    """
    fallback = REMINDER_FALLBACK_TEMPLATE.format(
        customer_name=facts.get("customer_name", "Customer"),
        shop_name=facts.get("shop_name", "Shop"),
        amount_text=facts.get("amount_text", "₹0.00"),
    )

    prompt = REMINDER_PROMPT.format(
        shop_name=facts.get("shop_name", "Shop"),
        customer_name=facts.get("customer_name", "Customer"),
        amount_text=facts.get("amount_text", "₹0.00"),
        days_text=facts.get("days_text", "recently"),
        language=language,
        tone=tone,
    )

    model = get_model_name()

    try:
        def _generate():
            return client.models.generate_content(
                model=model,
                contents=[prompt],
                config=types.GenerateContentConfig(temperature=0.3),
            )

        response = _call_with_retry(_generate)
        draft = (response.text or "").strip()

        # Guard 1: Must contain the exact amount string
        if facts.get("amount_text") not in draft:
            return fallback

        # Guard 2: Max 600 characters
        if len(draft) > 600:
            return fallback

        # Guard 3: Must not contain names of other customers
        if other_customers:
            for other_name in other_customers:
                if other_name and other_name.lower() != facts.get("customer_name", "").lower():
                    if other_name.lower() in draft.lower():
                        return fallback

        return draft
    except Exception:
        return fallback


def create_chat(client: genai.Client, shop_name: str) -> Any:
    """Create scoped chat session with SYSTEM_PROMPT per spec.md §8.3 [PDF pattern]."""
    model = get_model_name()
    system_instruction = SYSTEM_PROMPT.format(shop_name=shop_name)
    config = types.GenerateContentConfig(system_instruction=system_instruction)
    return client.chats.create(model=model, config=config)
