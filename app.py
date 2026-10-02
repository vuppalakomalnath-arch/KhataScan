"""KhataScan — AI-Powered Handwritten Credit Book Digitiser.

UI Orchestration only (per spec.md §4 & §9).
"""

import streamlit as st
from config import REMINDER_LANGUAGES, get_secret
from db import create_shop, get_db, get_shop_by_whatsapp
from auth import (
    hash_pin,
    is_locked_out,
    normalize_whatsapp,
    record_failed_login,
    reset_login_attempts,
    validate_pin_format,
    verify_pin,
)


def init_session():
    """Initialize persistent Streamlit session keys."""
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
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_onboarding():
    """Render Screen A: Onboarding / Login form per spec.md §9."""
    st.title("📒 KhataScan")
    st.subheader("Sign in or Register your Khata Book")
    st.write(
        "Digitize your handwritten credit ledger (udhaar khata) in seconds. "
        "Review entries with AI, track dues, and send WhatsApp summaries."
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
                help="Your WhatsApp number with country code (e.g. +919876543210)",
            )
            pin_input = st.text_input(
                "Security PIN",
                type="password",
                placeholder="4-8 digit numeric PIN",
                help="Enter your 4-8 digit PIN to login or register.",
            )

        language_choice = st.selectbox(
            "Default Reminder Language",
            options=REMINDER_LANGUAGES,
            index=0,
        )

        st.caption(
            "🔒 **Privacy Disclosure:** Ledger photos are sent to the Gemini API for character extraction. "
            "Raw images are never stored on our servers. You can permanently delete your data anytime."
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

        # Attempt DB connection
        try:
            db = get_db()
        except Exception as e:
            st.error(
                f"⚠️ Database connection failed: {e}. "
                "Please ensure `MONGODB_URI` is correctly configured in `.streamlit/secrets.toml`."
            )
            return

        existing_shop = get_shop_by_whatsapp(db, normalized_phone)
        if existing_shop:
            # Login flow
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
            # Registration flow
            if not shop_name_input.strip() or not owner_name_input.strip():
                st.error("❌ Shop Name and Owner Name are required for new registration.")
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


def render_main_app():
    """Render Screen B: Main application per spec.md §9."""
    shop_name = st.session_state.get("shop_name", "My Shop")
    whatsapp = st.session_state.get("whatsapp", "")

    # Header
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.title("📒 KhataScan")
        st.caption(f"Logged in as **{shop_name}** — updates go to `{whatsapp}`")
    with col_h2:
        send_btn = st.button("📤 Send to WhatsApp", key="header_send_wa", disabled=True)
        if send_btn:
            st.info("WhatsApp dispatch will be wired in T12.")

    # Sidebar
    with st.sidebar:
        st.header(shop_name)
        st.write("📊 **Ledger Snapshot**")
        st.metric("Total Outstanding", "₹0.00")
        st.metric("Customers with Dues", "0")
        st.divider()

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["shop_id"] = None
            st.rerun()

        st.divider()
        with st.expander("⚠️ Danger Zone"):
            if st.button("🗑️ Delete My Data", type="primary", use_container_width=True):
                st.session_state["confirm_delete"] = True

            if st.session_state.get("confirm_delete", False):
                st.warning("Are you sure? This permanently deletes all your customers, ledger entries, and account!")
                c_del1, c_del2 = st.columns(2)
                with c_del1:
                    if st.button("Yes, Delete", type="primary"):
                        try:
                            from db import delete_all_shop_data
                            db = get_db()
                            delete_all_shop_data(db, st.session_state["shop_id"])
                        except Exception:
                            pass
                        st.session_state.clear()
                        st.success("All your data has been deleted.")
                        st.rerun()
                with c_del2:
                    if st.button("Cancel"):
                        st.session_state["confirm_delete"] = False
                        st.rerun()

    # Tabs
    tab_chat, tab_dues = st.tabs(["💬 Chat", "📋 Dues & Reminders"])
    with tab_chat:
        st.write("Upload a photo of your handwritten ledger page to begin digitizing.")
        uploaded_file = st.chat_input(
            "Ask a question about your ledger, or attach an image...",
            accept_file=True,
            file_type=["jpg", "jpeg", "png"],
        )
        if uploaded_file:
            st.info("File upload will be processed by vision pipeline in T06-T08.")

    with tab_dues:
        st.write("Customer dues, balances, and WhatsApp reminder generators will appear here.")


def main():
    st.set_page_config(page_title="KhataScan", page_icon="📒", layout="wide")
    init_session()

    if not st.session_state.get("logged_in", False):
        render_onboarding()
    else:
        render_main_app()


if __name__ == "__main__":
    main()
