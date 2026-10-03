# 📒 KhataScan

> Snap a page of your handwritten credit book (khata). Gemini reads every entry, you verify it, the app stores it in MongoDB, computes who owes what exact to the paisa, and texts you a dues summary on WhatsApp via Twilio.

---

## 1. Problem & Who It Helps
Small retail shops in India traditionally keep track of customer credit (*udhaar / baki*) in physical, handwritten notebooks in mixed languages (English, Hindi, Telugu) and varied numeral systems. 
- Calculating totals and aging balances by hand is time-consuming and error-prone.
- Chasing overdue payments is socially awkward and lacks structured communication.
- Existing generic bill splitters or receipt scanners fail to understand multi-customer ledgers with both credit (*udhaar*) and payment (*jama*) entries.

**KhataScan** empowers local shopkeepers by transforming photographed handwritten pages into persistent, schema-validated ledger records—ensuring the human remains in complete control before any data is saved.

---

## 2. Core Architecture: "AI Reads. Code Computes. Human Verifies."

```
[Handwritten Khata Page]
          │
          ▼
   1. imaging.py ─────────► Preprocess & strip EXIF/GPS, compute SHA-256
          │
          ▼
 2. gemini_service.py ───► Gemini Vision extraction to ExtractedPage JSON schema
          │
          ▼
    3. ledger.py ─────────► Automated flags (outliers, missing dates, total mismatch)
          │                Fuzzy match existing customer names (token set ratio)
          ▼
   4. UI Review ──────────► Human-in-the-loop: editable st.data_editor table
          │                (Save blocked until amounts and types are valid)
          ▼
      5. db.py ───────────► Multi-tenant MongoDB Atlas (strictly integer paise)
          │
          ▼
    6. ledger.py ─────────► Deterministic calculation: balances & aging
          │
          ▼
   7. whatsapp.py ────────► Single-line sanitized summary via Twilio Content Template
```

**Key Architectural Invariants:**
- **Zero AI Arithmetic:** Gemini never calculates monetary balances. Python pure functions compute all dues in integer paise (`amount_paise`), eliminating float rounding errors.
- **Human in the Loop:** Extracted data is strictly staged as pending until the shopkeeper explicitly reviews and clicks Save.
- **Tenant Isolation:** Every single database query and transaction is strictly isolated by `shop_id`.

---

## 3. Features Shipped

- 🔐 **PIN-Based Authentication:** PBKDF2-HMAC-SHA256 hashed PIN credentials with lockout protection after 5 failed attempts.
- 📸 **Vision Preprocessing:** Automated EXIF orientation transpose, aspect-ratio preserving downscaling to 2000px, JPEG re-encoding to strip location data, and SHA-256 duplicate page detection.
- 🤖 **Structured Extraction:** Gemini Vision prompt engineered to extract multi-customer entries (date, customer name, description, amount, credit/payment type, confidence) with automated JSON schema validation and retry/repair fallbacks.
- 🎯 **Fuzzy Customer Matching:** Powered by `rapidfuzz` token-set ratio to recognize existing customer accounts across spelling variants, with automatic tie detection.
- 📝 **Editable Verification Panel:** `st.data_editor` review table with validation flags (`low_confidence`, `missing_amount`, `amount_outlier`, `future_date`, `total_mismatch`).
- 💰 **Exact Balance Engine:** Credits minus payments calculated deterministically to integer paise with payment aging tracking ("days since last payment").
- 💬 **Context-Injected Ledger Chat:** Conversational assistant grounded exclusively in code-computed ledger facts.
- 📱 **Twilio WhatsApp Integration:** One-click dispatch of formatted dues summary to the shopkeeper's phone using WhatsApp Content Templates.
- 🌐 **Multilingual Reminders & Deep Links:** AI drafts polite reminders in English, Hindi, or Telugu with strict factual guards, paired with direct `wa.me` links for customers.
- 📥 **CSV Export:** One-click export of customer balances and aging for offline recordkeeping.
- 🛡️ **Privacy & "Delete My Data":** Complete, permanent erasure of all shop records upon request.

---

## 4. Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| **Frontend** | Streamlit | Rapid, responsive Python UI with native data editors and mobile accessibility |
| **AI Vision & Chat** | Google GenAI SDK (`google-genai`) | Multimodal extraction with strict JSON schema constraints |
| **Database** | MongoDB Atlas via `pymongo` | Scalable cloud document database with compound indexes |
| **WhatsApp Dispatch** | Twilio REST API | Official WhatsApp Business messaging via approved Content Templates |
| **Data Validation** | Pydantic v2 | Type validation and schema guarantees for all AI responses |
| **Fuzzy Matching** | RapidFuzz | High-performance C++ based string matching for customer names |
| **Image Processing**| Pillow (PIL) | EXIF orientation normalization, downscaling, and privacy stripping |
| **Testing** | Pytest | 100% pure-function test coverage without network dependencies |

---

## 5. Local Setup Guide

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Git

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/<your-username>/khatascan.git
cd khatascan

python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Secrets
Copy the template to your local secrets file:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml` with your credentials:
```toml
GEMINI_API_KEY = "your-gemini-api-key"

MONGODB_URI = "mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DB = "khatascan"

TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN = "your-twilio-auth-token"
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
TWILIO_CONTENT_SID = "HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

MODEL_NAME = "gemini-2.5-flash"
DEFAULT_COUNTRY_CODE = "91"
```

### 3. Twilio WhatsApp Sandbox Setup
1. Log into your Twilio Console and navigate to **Messaging → Try it out → Send a WhatsApp message**.
2. From your WhatsApp phone, send the join keyword (e.g. `join <code-word>`) to `+1 415 523 8886`.
3. In Twilio Content Template Builder, create a text template:
   - Body: `Hi {{1}}, here's your KhataScan summary:\n\n{{2}}`
   - Copy the Content SID (`HX...`) into `TWILIO_CONTENT_SID`.

### 4. Run the Application
```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## 6. Secrets Table

| Secret Key | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini 2.5/3.5 Vision and Chat API calls |
| `MONGODB_URI` | Yes | MongoDB Atlas connection string with TLS |
| `MONGODB_DB` | No | Database name (defaults to `khatascan`) |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account identifier |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio API authentication token |
| `TWILIO_WHATSAPP_FROM` | Yes | Twilio WhatsApp sender (default sandbox: `whatsapp:+14155238886`) |
| `TWILIO_CONTENT_SID` | Yes | Approved WhatsApp Content Template SID (`HX...`) |
| `MODEL_NAME` | No | Model name override (defaults to `gemini-2.5-flash`) |
| `DEFAULT_COUNTRY_CODE` | No | Default telephone prefix (defaults to `91` for India) |

---

## 7. Running Unit Tests

KhataScan enforces pure functions for all financial logic, deduplication, validation, and string sanitization. All unit tests run offline in seconds without requiring active database or cloud API access:

```bash
pytest
```

Test suite coverage:
- `test_money.py`: Integer paise conversions, round-half-up math, Indian number formatting (`₹1,250.00`).
- `test_ledger.py`: Validation flags, page total mismatch, deduplication hashes, balance and aging logic.
- `test_matching.py`: RapidFuzz customer matching, auto-merge thresholds, tiebreaker safety.
- `test_whatsapp.py`: Content Template variable sanitization (newline removal, whitespace collapse), summary building, `wa.me` links.
- `test_auth.py`: Salted PBKDF2 PIN hashing and verification, E.164 phone normalization.
- `test_imaging.py`: Resolution guards, aspect-ratio downscaling, SHA-256 fingerprinting.
- `test_gemini_service.py`: JSON schema validation, reminder guardrails, fallback triggers.

---

## 8. Privacy, Security & Limitations

- **Privacy by Design:** Raw ledger images are never saved to disk or database. Preprocessing strips all GPS/camera EXIF metadata.
- **Third-Party Processing:** Images are sent in memory to Google Gemini API for OCR and character extraction.
- **Twilio Sandbox:** In sandbox mode, Twilio only delivers WhatsApp messages to phone numbers that have opted in via the sandbox join code within the last 72 hours. Customer reminder drafts use direct `wa.me` browser links that do not require Twilio opt-in.
- **Data Erasure:** Shop owners can permanently delete their account and all associated customer and ledger records with one click via the "Delete My Data" feature.

---

## 9. 2-Minute Demo Script

1. **Sign Up:** Register your shop name (e.g., *Ramesh Kirana Store*), WhatsApp number, and a 4-digit PIN.
2. **Upload Ledger:** In the Chat tab, upload `data/samples/sample_ledger_1.png`.
3. **Review & Correct:** Inspect the extracted entries in the `st.data_editor` table. Notice auto-matched customer names, flags, and credit/payment types. Edit an amount or toggle checkboxes.
4. **Save Entries:** Click **✅ Save Entries**. Watch the sidebar metrics immediately update with exact outstanding dues.
5. **Ledger Chat:** Ask the assistant: *"Who owes me the most?"* Notice the AI answers strictly from the code-computed context.
6. **Generate Reminders:** In the **Dues & Reminders** tab, pick a customer, choose Telugu or Hindi, and generate a polite reminder draft. Click **📲 Open WhatsApp** to inspect the ready-to-send message.
7. **Send WhatsApp Summary:** Click **📤 Send to WhatsApp** in the top header. Confirm the delivery of the single-line dues summary directly to your mobile device.

---

## 10. Live Demo Link & Repository

- **Live Application:** [https://khatascan.streamlit.app/](https://khatascan.streamlit.app/)
- **GitHub Repository:** [https://github.com/vuppalakomalnath-arch/KhataScan](https://github.com/vuppalakomalnath-arch/KhataScan)

---

## 11. Resume Bullets

- Built **KhataScan**, a Gemini-vision + Streamlit web app that digitises handwritten shop credit ledgers into schema-validated MongoDB records, with an interactive human verification step before persisting data.
- Designed a hybrid architecture where the multimodal LLM extracts rows and drafts communications while deterministic Python logic handles currency conversion (integer paise), duplicate transaction detection, fuzzy customer matching, and balances.
- Delivered automated dues summaries and multilingual payment reminders through Twilio WhatsApp (Content Templates) and direct WhatsApp deep links.
- Implemented robust multi-tenant data isolation, security hardening with salted PBKDF2 hashing, and a one-click 'Delete My Data' privacy compliance mechanism.
