"""KhataScan — AI-Powered Handwritten Credit Book Digitiser.

Source of Truth: spec.md §4, §9, §10
Architecture: AI reads. Code computes. Human verifies.
"""

from datetime import datetime, timezone
import io
import json
from typing import Any, Dict, List, Optional
import pandas as pd
from PIL import Image
import streamlit as st

from auth import (
    hash_pin,
    is_locked_out,
    normalize_whatsapp,
    record_failed_login,
    reset_login_attempts,
    validate_pin_format,
    verify_pin,
)
from config import (
    DEFAULT_COUNTRY_CODE,
    REMINDER_LANGUAGES,
    get_secret,
)
from db import (
    create_shop,
    delete_all_shop_data,
    get_db,
    get_page_by_hash,
    get_shop_by_whatsapp,
    insert_page,
    list_customers,
    list_entries,
    log_send,
    update_customer_phone,
    update_page_status,
)
from gemini_service import (
    ExtractionError,
    create_chat,
    draft_reminder,
    extract_page,
    get_gemini_client,
)
from imaging import (
    ImageTooLarge,
    ImageTooSmall,
    preprocess,
    sha256_hex,
)
from ledger import (
    build_ledger_context,
    build_review_rows,
    compute_balances,
    save_reviewed_entries,
    validate_page,
)
from prompts import PROMPT_VERSION, WELCOME_MESSAGE_TEMPLATE
from schemas import (
    CustomerBalance,
    ExtractedPage,
    ReviewRow,
    format_inr,
)
from whatsapp import (
    build_summary,
    get_twilio_client,
    sanitize_template_var,
    send_whatsapp,
    wa_link,
)


def init_session():
    """Initialize persistent Streamlit session keys per spec.md §9."""
    defaults = {
        "logged_in": False,
        "shop_id": None,
        "shop_name": None,
        "owner_name": None,
        "whatsapp": None,
        "language": "English",
        "chat": None,
        "messages": [],
        "pending_page_id": None,
        "pending_rows": None,
        "pending_image_hash": None,
        "pending_total_mismatch": False,
        "login_attempts": 0,
        "locked_until": 0,
        "drafts": {},
        "confirm_delete": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# =========================================================
# Screen A: Onboarding & Authentication
# =========================================================

def render_onboarding():
    st.title("📒 KhataScan")
    st.subheader("Digitize your handwritten credit book (khata)")
    st.write(
        "Upload handwritten ledger photos, review with AI, compute dues exact to the paisa, "
        "and receive dues summaries directly on your WhatsApp."
    )

    locked, wait_secs = is_locked_out()
    if locked:
        st.error(f"⛔ Too many failed attempts. Account temporarily locked. Please try again in {wait_secs} seconds.")
        return

    with st.form("onboarding_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            shop_name_input = st.text_input("Shop Name", placeholder="e.g. Ramesh Kirana Store")
            owner_name_input = st.text_input("Owner Name", placeholder="e.g. Ramesh Kumar")
        with col2:
            phone_input = st.text_input(
                "WhatsApp Number",
                placeholder="+91XXXXXXXXXX",
                help="Enter your WhatsApp number with country code (e.g. +919876543210)",
            )
            pin_input = st.text_input(
                "Security PIN",
                type="password",
                placeholder="4-8 digit numeric PIN",
                help="Enter 4-8 digit PIN to login or register.",
            )

        language_choice = st.selectbox(
            "Default Reminder Language",
            options=REMINDER_LANGUAGES,
            index=0,
        )

        st.caption(
            "🔒 **Privacy Disclosure:** Ledger photos are sent to Google Gemini API for character extraction. "
            "Raw images are never stored on our servers. You may permanently delete all your data at any time."
        )

        submit_btn = st.form_submit_button("Continue to Ledger", use_container_width=True)

    if submit_btn:
        normalized_phone = normalize_whatsapp(phone_input)
        if not normalized_phone:
            st.error("❌ Please enter a valid WhatsApp phone number with country code (e.g. +91XXXXXXXXXX).")
            return

        if not validate_pin_format(pin_input):
            st.error("❌ Security PIN must be 4 to 8 numeric digits.")
            return

        try:
            db = get_db()
        except Exception as e:
            st.error(
                f"⚠️ Database connection failed: {e}. "
                "Please configure `MONGODB_URI` in `.streamlit/secrets.toml`."
            )
            return

        existing_shop = get_shop_by_whatsapp(db, normalized_phone)
        if existing_shop:
            if verify_pin(pin_input, existing_shop["pin_hash"], existing_shop["pin_salt"]):
                reset_login_attempts()
                st.session_state["logged_in"] = True
                st.session_state["shop_id"] = existing_shop["_id"]
                st.session_state["shop_name"] = existing_shop.get("shop_name", "My Shop")
                st.session_state["owner_name"] = existing_shop.get("owner_name", "")
                st.session_state["whatsapp"] = existing_shop["whatsapp"]
                st.session_state["language"] = existing_shop.get("language", language_choice)
                st.success(f"Welcome back, {st.session_state['shop_name']}!")
                st.rerun()
            else:
                attempts = record_failed_login()
                st.error(f"❌ Incorrect PIN. Attempt {attempts} of 5.")
                if attempts >= 5:
                    st.rerun()
        else:
            if not shop_name_input.strip() or not owner_name_input.strip():
                st.error("❌ Shop Name and Owner Name are required to register a new khata account.")
                return

            pin_hash, pin_salt = hash_pin(pin_input)
            new_shop = create_shop(
                db=db,
                whatsapp=normalized_phone,
                shop_name=shop_name_input.strip(),
                owner_name=owner_name_input.strip(),
                pin_hash=pin_hash,
                pin_salt=pin_salt,
                language=language_choice,
            )
            reset_login_attempts()
            st.session_state["logged_in"] = True
            st.session_state["shop_id"] = new_shop["_id"]
            st.session_state["shop_name"] = new_shop["shop_name"]
            st.session_state["owner_name"] = new_shop["owner_name"]
            st.session_state["whatsapp"] = new_shop["whatsapp"]
            st.session_state["language"] = new_shop["language"]
            st.success(f"Account registered successfully! Welcome, {new_shop['shop_name']}!")
            st.rerun()


# =========================================================
# Screen B: Main App Layout & Core Flows
# =========================================================

def render_main_app():
    shop_id = st.session_state["shop_id"]
    shop_name = st.session_state.get("shop_name", "My Shop")
    owner_name = st.session_state.get("owner_name", "")
    whatsapp = st.session_state.get("whatsapp", "")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Connect DB & Load current data
    try:
        db = get_db()
        customers = list_customers(db, shop_id)
        entries = list_entries(db, shop_id)
        current_balances = compute_balances(entries, customers, today_iso)
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    total_due_paise = sum(b.balance_paise for b in current_balances if b.balance_paise > 0)
    customers_with_dues = sum(1 for b in current_balances if b.balance_paise > 0)

    # ---------------- Top Header ----------------
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.title("📒 KhataScan")
        st.caption(f"Logged in as **{shop_name}** — updates go to `{whatsapp}`")

    with col_h2:
        can_send_wa = total_due_paise > 0
        if st.button("📤 Send to WhatsApp", key="header_send_wa", disabled=not can_send_wa, use_container_width=True):
            _dispatch_whatsapp_summary(db, shop_id, shop_name, owner_name, whatsapp, current_balances, today_iso)

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.header(shop_name)
        st.write("📊 **Ledger Snapshot**")
        st.metric("Total Outstanding", format_inr(total_due_paise))
        st.metric("Customers with Dues", f"{customers_with_dues}")
        st.divider()

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

        st.divider()
        with st.expander("⚠️ Danger Zone"):
            if st.button("🗑️ Delete My Data", type="primary", use_container_width=True):
                st.session_state["confirm_delete"] = True

            if st.session_state.get("confirm_delete", False):
                st.warning("Permanently delete this shop and all customer/ledger data?")
                c_del1, c_del2 = st.columns(2)
                with c_del1:
                    if st.button("Yes, Delete Everything", type="primary"):
                        delete_all_shop_data(db, shop_id)
                        st.session_state.clear()
                        st.success("All your data has been permanently deleted.")
                        st.rerun()
                with c_del2:
                    if st.button("Cancel"):
                        st.session_state["confirm_delete"] = False
                        st.rerun()

    # ---------------- Navigation Tabs ----------------
    tab_chat, tab_dues = st.tabs(["💬 Chat & Vision", "📋 Dues & Reminders"])

    with tab_chat:
        _render_chat_tab(db, shop_id, shop_name, owner_name, current_balances, customers, today_iso)

    with tab_dues:
        _render_dues_tab(db, shop_id, shop_name, current_balances, customers, today_iso)


# =========================================================
# Chat & Vision Pipeline Flow (§10.1 & §9)
# =========================================================

def _render_chat_tab(
    db: Any,
    shop_id: Any,
    shop_name: str,
    owner_name: str,
    balances: List[CustomerBalance],
    customers: List[Dict[str, Any]],
    today_iso: str,
):
    # Welcome message on first load
    if not st.session_state.get("messages"):
        welcome_txt = WELCOME_MESSAGE_TEMPLATE.format(name=owner_name or shop_name)
        st.session_state["messages"].append({"role": "assistant", "content": welcome_txt})

    # Render chat messages
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Review Panel (renders if pending_rows exist)
    if st.session_state.get("pending_rows"):
        _render_review_panel(db, shop_id, customers)

    # Chat Input with File Upload per spec.md §9
    user_input = st.chat_input(
        "Ask about customer dues, or attach a photo of your ledger page...",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    )

    if user_input:
        # Check if an image file was attached
        uploaded_file = getattr(user_input, "files", None)
        text_prompt = getattr(user_input, "text", "") or ""

        if uploaded_file and len(uploaded_file) > 0:
            file_obj = uploaded_file[0]
            _process_uploaded_page(db, shop_id, file_obj, customers, today_iso)
        elif text_prompt.strip():
            _handle_chat_text(shop_name, text_prompt, balances, today_iso)


def _process_uploaded_page(
    db: Any,
    shop_id: Any,
    file_obj: Any,
    customers: List[Dict[str, Any]],
    today_iso: str,
):
    """Execute upload -> preprocess -> Gemini extraction -> review setup (§10.1)."""
    raw_bytes = file_obj.read()

    # Step 1: Preprocess and sanitize image
    try:
        clean_bytes = preprocess(raw_bytes)
    except ImageTooSmall as e:
        st.error(f"❌ {e}")
        return
    except ImageTooLarge as e:
        st.error(f"❌ {e}")
        return
    except Exception as e:
        st.error(f"❌ Failed to process image: {e}")
        return

    # Step 2: Duplicate check via SHA-256
    img_hash = sha256_hex(clean_bytes)
    existing_page = get_page_by_hash(db, shop_id, img_hash)
    if existing_page and existing_page.get("status") == "imported":
        st.warning("⚠️ This ledger page has already been imported! Duplicate entries will be skipped.")

    # Step 3: Extract with Gemini
    with st.spinner("🔍 Reading handwritten ledger page with Gemini..."):
        try:
            client = get_gemini_client()
            extracted_page: ExtractedPage = extract_page(client, clean_bytes, today_iso)
        except Exception as e:
            st.error(f"❌ Extraction error: {e}")
            return

    if not extracted_page.is_ledger_page:
        st.error("❌ That doesn't look like a ledger page. Please upload a clear photo of your khata book.")
        return

    if extracted_page.image_quality == "poor":
        st.warning("⚠️ The image quality was low. Please double-check amounts and names carefully.")

    # Step 4: Insert pending page record
    page_id = insert_page(
        db=db,
        shop_id=shop_id,
        image_sha256=img_hash,
        extraction=extracted_page.model_dump(),
        model_name=get_secret("MODEL_NAME", "gemini-2.5-flash"),
        prompt_version=PROMPT_VERSION,
        status="pending",
    )

    # Step 5: Validate and build review rows
    validated_rows, total_mismatch = validate_page(extracted_page, today_iso)
    review_rows = build_review_rows(validated_rows, customers, today_iso)

    st.session_state["pending_page_id"] = page_id
    st.session_state["pending_rows"] = review_rows
    st.session_state["pending_image_hash"] = img_hash
    st.session_state["pending_total_mismatch"] = total_mismatch

    # Assistant summary message
    n_rows = len(review_rows)
    unique_custs = len({r.customer for r in review_rows})
    flagged = sum(1 for r in review_rows if r.flags != "clean")
    summary_msg = (
        f"📸 Page scanned successfully! Found **{n_rows} rows** for **{unique_custs} customers**; "
        f"**{flagged} need a closer look**. Please review and confirm the table below before saving."
    )
    st.session_state["messages"].append({"role": "assistant", "content": summary_msg})
    st.rerun()


def _render_review_panel(
    db: Any,
    shop_id: Any,
    customers: List[Dict[str, Any]],
):
    """Render editable Review Table under chat per spec.md §9."""
    st.markdown("### 📝 Review & Verify Extracted Ledger Entries")
    st.caption("AI reads. Code computes. Human verifies. Review and edit values before saving to your khata.")

    if st.session_state.get("pending_total_mismatch"):
        st.warning(
            "⚠️ **Page Total Mismatch:** The stated grand total written on the page does not match the sum of "
            "credit entries. Please review individual row amounts."
        )

    rows: List[ReviewRow] = st.session_state["pending_rows"]

    # Build options for Customer selectbox
    existing_names = [c["display_name"] for c in customers if c.get("display_name")]
    raw_names = [r.original_name_raw for r in rows if r.original_name_raw]
    customer_options = sorted(list(set(existing_names + [f"NEW: {n}" for n in raw_names if n])))
    if "NEW: Unknown" not in customer_options:
        customer_options.append("NEW: Unknown")

    table_data = []
    for r in rows:
        table_data.append({
            "Include": r.include,
            "⚠": r.warning,
            "Date": r.date,
            "Customer": r.customer if r.customer in customer_options else customer_options[0],
            "Description": r.description,
            "Type": r.entry_type,
            "Amount (₹)": float(r.amount),
            "Confidence": float(r.confidence),
            "Flags": r.flags,
            "_row_number": r.row_number,
        })

    df = pd.DataFrame(table_data)

    column_config = {
        "Include": st.column_config.CheckboxColumn("Include", help="Select to save this entry"),
        "⚠": st.column_config.TextColumn("Status", disabled=True, width="small"),
        "Date": st.column_config.TextColumn("Date", required=True),
        "Customer": st.column_config.SelectboxColumn("Customer", options=customer_options, required=True),
        "Description": st.column_config.TextColumn("Description"),
        "Type": st.column_config.SelectboxColumn("Type", options=["credit", "payment"], required=True),
        "Amount (₹)": st.column_config.NumberColumn("Amount (₹)", min_value=0.01, step=1.0, format="₹%.2f", required=True),
        "Confidence": st.column_config.NumberColumn("Confidence", disabled=True, format="%.2f", width="small"),
        "Flags": st.column_config.TextColumn("Flags", disabled=True),
        "_row_number": None,
    }

    edited_df = st.data_editor(
        df,
        column_config=column_config,
        disabled=["⚠", "Confidence", "Flags"],
        use_container_width=True,
        num_rows="dynamic",
        key="ledger_data_editor",
    )

    # Validate before enabling Save
    included_records = edited_df[edited_df["Include"] == True]
    num_included = len(included_records)

    invalid_rows = []
    for idx, rec in included_records.iterrows():
        amt = rec.get("Amount (₹)", 0.0)
        etype = rec.get("Type", "")
        if amt is None or amt <= 0 or etype not in ("credit", "payment"):
            invalid_rows.append(idx + 1)

    can_save = (num_included > 0) and (len(invalid_rows) == 0)

    col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 4])
    with col_btn1:
        if st.button(f"✅ Save {num_included} entries", disabled=not can_save, type="primary"):
            updated_rows = []
            for _, r in edited_df.iterrows():
                updated_rows.append(ReviewRow(
                    row_number=int(r.get("_row_number", 0)),
                    include=bool(r.get("Include", False)),
                    warning=str(r.get("⚠", "")),
                    date=str(r.get("Date", "")),
                    customer=str(r.get("Customer", "")),
                    description=str(r.get("Description", "")),
                    entry_type=str(r.get("Type", "credit")),
                    amount=float(r.get("Amount (₹)", 0.0)),
                    confidence=float(r.get("Confidence", 0.0)),
                    flags=str(r.get("Flags", "")),
                ))

            res = save_reviewed_entries(
                db=db,
                shop_id=shop_id,
                page_id=st.session_state.get("pending_page_id"),
                rows=updated_rows,
                existing_customers=customers,
            )

            st.session_state["pending_rows"] = None
            st.session_state["pending_page_id"] = None
            st.session_state["pending_total_mismatch"] = False

            save_msg = f"🎉 Successfully saved **{res['saved']} entries** into your khata!"
            if res.get("duplicates", 0) > 0:
                save_msg += f" (Skipped {res['duplicates']} duplicate transactions)"
            st.session_state["messages"].append({"role": "assistant", "content": save_msg})
            st.rerun()

    with col_btn2:
        if st.button("🗑 Discard Page"):
            if st.session_state.get("pending_page_id"):
                update_page_status(db, st.session_state["pending_page_id"], shop_id, "discarded")
            st.session_state["pending_rows"] = None
            st.session_state["pending_page_id"] = None
            st.session_state["pending_total_mismatch"] = False
            st.session_state["messages"].append({"role": "assistant", "content": "Ledger page discarded."})
            st.rerun()

    with col_btn3:
        if invalid_rows:
            st.warning(f"Row {invalid_rows[0]} requires an amount > ₹0 and a valid type before saving.")


def _handle_chat_text(
    shop_name: str,
    prompt: str,
    balances: List[CustomerBalance],
    today_iso: str,
):
    """Handle text chat using context injection per spec.md §7.2 & §8.3."""
    st.session_state["messages"].append({"role": "user", "content": prompt})

    try:
        client = get_gemini_client()
        if "chat" not in st.session_state or st.session_state["chat"] is None:
            st.session_state["chat"] = create_chat(client, shop_name)

        chat_session = st.session_state["chat"]
        context_block = build_ledger_context(balances, today_iso)
        injected_message = f"{context_block}\n\nUser Question: {prompt}"

        with st.spinner("Thinking..."):
            response = chat_session.send_message(injected_message)
            reply_text = response.text or "I don't have that information in your ledger context."

        st.session_state["messages"].append({"role": "assistant", "content": reply_text})
        st.rerun()
    except Exception as e:
        err_msg = f"Sorry, could not process request: {e}"
        st.session_state["messages"].append({"role": "assistant", "content": err_msg})
        st.rerun()


# =========================================================
# Dues & Reminders Tab (§9 & §10.4)
# =========================================================

def _render_dues_tab(
    db: Any,
    shop_id: Any,
    shop_name: str,
    balances: List[CustomerBalance],
    customers: List[Dict[str, Any]],
    today_iso: str,
):
    st.subheader("📋 Customer Balances & Dues")

    if not balances:
        st.info("No ledger entries yet. Upload a ledger page in the Chat tab to start tracking dues.")
        return

    cust_phone_map = {str(c["_id"]): c.get("phone", "") for c in customers}

    # Display Balances Table
    table_rows = []
    for b in balances:
        table_rows.append({
            "Customer": b.name,
            "Balance Due": format_inr(b.balance_paise),
            "Status": "Due" if b.balance_paise > 0 else ("Advance Paid" if b.balance_paise < 0 else "Cleared"),
            "Days Since Payment": f"{b.days_since_payment}d" if b.days_since_payment is not None else "No payment",
            "Last Activity": b.last_activity or "None",
            "Phone": cust_phone_map.get(b.customer_id, ""),
            "_customer_id": b.customer_id,
        })

    df = pd.DataFrame(table_rows)
    export_df = df[["Customer", "Balance Due", "Status", "Days Since Payment", "Last Activity", "Phone"]]
    st.dataframe(
        export_df,
        use_container_width=True,
        hide_index=True,
    )

    # P2: CSV export
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Export Balances to CSV",
        data=csv_bytes,
        file_name=f"khatascan_balances_{today_iso}.csv",
        mime="text/csv",
    )

    # Customer Phone Number Manager
    with st.expander("📞 Update Customer Phone Numbers (for WhatsApp Reminders)"):
        c_sel = st.selectbox("Select Customer", options=balances, format_func=lambda b: b.name)
        if c_sel:
            curr_phone = cust_phone_map.get(c_sel.customer_id, "")
            new_phone = st.text_input("Customer Phone (E.164 e.g. +919876543210)", value=curr_phone, key=f"phone_{c_sel.customer_id}")
            if st.button("Save Phone", key="save_phone_btn"):
                norm = normalize_whatsapp(new_phone)
                if norm:
                    update_customer_phone(db, shop_id, c_sel.customer_id, norm)
                    st.success(f"Updated phone for {c_sel.name} to {norm}")
                    st.rerun()
                else:
                    st.error("Please enter a valid phone number with country code.")

    st.divider()

    # Reminders Generator
    st.subheader("💬 Generate Payment Reminders")
    debtors = [b for b in balances if b.balance_paise > 0]
    if not debtors:
        st.write("All customer balances are cleared! No reminders to send.")
        return

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        reminder_lang = st.selectbox("Reminder Language", options=REMINDER_LANGUAGES, index=0)
    with col_r2:
        reminder_tone = st.selectbox("Tone", options=["gentle", "firm"], index=0)

    selected_cust_names = st.multiselect(
        "Select Customers to Remind (max 10)",
        options=[b.name for b in debtors],
        default=[b.name for b in debtors[:3]],
        max_selections=10,
    )

    if st.button("✨ Generate AI Reminder Drafts"):
        try:
            client = get_gemini_client()
        except Exception as e:
            st.error(f"Gemini client unavailable: {e}")
            return

        all_names = [b.name for b in balances]
        drafts = {}
        for cname in selected_cust_names:
            target = next(b for b in debtors if b.name == cname)
            days_str = f"{target.days_since_payment} days" if target.days_since_payment is not None else "some time"
            facts = {
                "shop_name": shop_name,
                "customer_name": target.name,
                "amount_text": format_inr(target.balance_paise),
                "days_text": days_str,
            }
            draft = draft_reminder(client, facts, language=reminder_lang, tone=reminder_tone, other_customers=all_names)
            drafts[target.customer_id] = {
                "name": target.name,
                "draft": draft,
                "phone": cust_phone_map.get(target.customer_id, ""),
            }
        st.session_state["drafts"] = drafts
        st.rerun()

    # Render generated drafts
    if st.session_state.get("drafts"):
        st.markdown("#### Drafted Reminders")
        for cid, dinfo in list(st.session_state["drafts"].items()):
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                edited_draft = st.text_area(
                    f"Reminder for {dinfo['name']}",
                    value=dinfo["draft"],
                    key=f"draft_{cid}",
                    height=100,
                )
                st.session_state["drafts"][cid]["draft"] = edited_draft
            with col_d2:
                phone = dinfo.get("phone")
                if phone:
                    link = wa_link(phone, edited_draft)
                    if link:
                        st.link_button("📲 Open WhatsApp", link, use_container_width=True)
                else:
                    st.caption("No phone added. Add phone above to send via WhatsApp.")

        st.divider()
        if st.button("📤 Send All Drafts to My WhatsApp (Summary)"):
            all_text = " | ".join(f"{d['name']}: {d['draft']}" for d in st.session_state["drafts"].values())
            cleaned_summary = sanitize_template_var(all_text)
            twilio_client = get_twilio_client()
            ok, info = send_whatsapp(
                client=twilio_client,
                from_=get_secret("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"),
                to_number=st.session_state["whatsapp"],
                user_name=shop_name,
                summary=cleaned_summary,
                content_sid=get_secret("TWILIO_CONTENT_SID"),
            )
            log_send(db, shop_id, "reminders", info if ok else None, ok, info)
            if ok:
                st.success("Sent all drafts to your WhatsApp! 📲")
            else:
                st.error(f"Twilio dispatch failed: {info}")


# =========================================================
# WhatsApp Summary Dispatcher (T12 & §8.5)
# =========================================================

def _dispatch_whatsapp_summary(
    db: Any,
    shop_id: Any,
    shop_name: str,
    owner_name: str,
    whatsapp: str,
    balances: List[CustomerBalance],
    today_iso: str,
):
    """Deliver single-line dues summary to the shopkeeper's phone via Twilio WhatsApp."""
    summary_text = build_summary(shop_name, balances, today_iso)
    twilio_client = get_twilio_client()
    from_num = get_secret("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    content_sid = get_secret("TWILIO_CONTENT_SID")

    with st.spinner("Dispatching summary to your WhatsApp..."):
        ok, info = send_whatsapp(
            client=twilio_client,
            from_=from_num,
            to_number=whatsapp,
            user_name=owner_name or shop_name,
            summary=summary_text,
            content_sid=content_sid,
        )

    log_send(db, shop_id, "summary", info if ok else None, ok, info)

    if ok:
        st.success("Sent! Check your WhatsApp 📲")
    else:
        st.error(
            f"❌ WhatsApp delivery failed: {info}\n\n"
            "If using Twilio Sandbox, verify you have sent the sandbox join code to +1 415 523 8886 "
            "and that `TWILIO_CONTENT_SID` matches your template."
        )


# =========================================================
# App Entry Point
# =========================================================

def main():
    st.set_page_config(
        page_title="KhataScan",
        page_icon="📒",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session()

    if not st.session_state.get("logged_in", False):
        render_onboarding()
    else:
        render_main_app()


if __name__ == "__main__":
    main()
