# Architecture & Implementation Decisions

This document tracks engineering decisions, verifications, and trade-offs made during the KhataScan build following `spec.md`.

## Decision Log

- **2026-10-02 (T01): Initial Setup & Repository Isolation**
  - Isolated dedicated Git repository inside project folder `c:\Users\sv computers\Desktop\KhataScan`.
  - Configured `.gitignore` to strictly ignore `.streamlit/secrets.toml`, `venv/`, `__pycache__/`, `.env`.
  - Created `.streamlit/secrets.toml.example` with documented secret definitions.
  - Initialized Python virtual environment with all required dependencies from `requirements.txt`.

- **2026-10-02 (T02): Money Representation & Indian Number Formatting**
  - Enforced `rupees_to_paise()` round-half-up quantization using Python `decimal.Decimal` to avoid floating point math anomalies.
  - Implemented standard Indian numbering format (e.g., `1,25,000.00` and `1,250.00`) inside `format_inr()`.
  - Added unit test suite in `tests/test_money.py` verifying exact paisa conversion and formatting.

- **2026-10-02 (T03): Multi-Tenant Data Isolation in MongoDB**
  - Configured idempotent index creation on startup for `shops`, `customers`, `pages`, `entries`, and `sends`.
  - Enforced mandatory `shop_id` scoping across all customer and entry CRUD operations.
  - Implemented `delete_all_shop_data()` to fulfill the "Delete My Data" privacy requirement.

- **2026-10-02 (T04): Security & Authentication**
  - Implemented PBKDF2-HMAC-SHA256 password hashing with 200,000 iterations and unique 16-byte random salts.
  - Implemented constant-time hash verification via `hmac.compare_digest`.
  - Added session lockout mechanism after 5 failed attempts (300 seconds delay).
  - Implemented E.164 phone normalization with standard international format validation.

- **2026-10-02 (T05 & T07): Gemini API Integration & Robust Extraction**
  - Configured `@st.cache_resource` for `get_gemini_client()` to prevent client re-instantiation across Streamlit reruns.
  - Configured structured output with `response_mime_type="application/json"` and `response_schema=ExtractedPage`.
  - Added exponential backoff retry on 429/5xx status codes and one-shot repair prompting for any malformed JSON outputs.
  - Implemented strict code guards on reminder drafts: exact amount presence, max 600 characters, no third-party name leakage.

- **2026-10-02 (T06): Image Processing & Privacy by Design**
  - Preprocessed images using Pillow: automated EXIF orientation transpose, downscaled to 2000px max side, rejected below 600px min side.
  - Stripped all EXIF/GPS metadata via JPEG re-encoding before API transit.
  - Raw images are never stored in the database or filesystem; only SHA-256 fingerprints are retained for duplicate detection.

- **2026-10-02 (T08 - T10): Human-in-the-Loop Review & Ledger Balances**
  - Integrated `st.data_editor` review panel enabling shopkeepers to review, edit, or reject entries before saving.
  - Save button is programmatically disabled if any included row has missing or non-positive amounts or undefined entry types.
  - Implemented deterministic `compute_balances()` for credits minus payments and payment aging ("days since last payment").

- **2026-10-02 (T11 & T12): WhatsApp Template Compliance**
  - Sanitized WhatsApp template variables by replacing all newlines, tabs, and consecutive spaces with single spaces, formatted with ` | ` separators to meet WhatsApp Business API constraints.
  - Generated direct `wa.me` links for customer payment reminders without requiring sandbox opt-in.
  - Enabled one-tap summary dispatch via Twilio WhatsApp Content Templates.

- **2026-10-02 (T14 - T21): Depth, Chat & Exports**
  - Integrated `rapidfuzz.fuzz.token_set_ratio` with tiebreaker thresholds to prevent false auto-merges of ambiguous names (e.g. Ramesh vs Ramesh Kumar/Ramesh Gupta).
  - Injected latest code-computed ledger context into chat interactions so the LLM never fabricates financial balances.
  - Added CSV export for customer records and balance statements.
