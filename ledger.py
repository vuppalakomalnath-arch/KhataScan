"""Ledger business logic: validation, fuzzy customer matching, balances, deduplication.

Source of Truth: spec.md §8.4
Core Principle: AI reads. Code computes. Human verifies.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from rapidfuzz import fuzz

from config import (
    AMOUNT_OUTLIER_RUPEES,
    CONF_REVIEW_THRESHOLD,
    MATCH_AUTO,
    MATCH_SUGGEST,
    MATCH_TIE_MARGIN,
)
from db import insert_entries, update_page_status, upsert_customer
from schemas import (
    CustomerBalance,
    ExtractedEntry,
    ExtractedPage,
    MatchResult,
    ReviewRow,
    format_inr,
    rupees_to_paise,
)

HONORIFICS = {
    "shri", "sri", "mr", "mrs", "ms", "smt", "bhai", "ji", "garu", "anna", "akka"
}


def normalize_name(s: Optional[str]) -> str:
    """Normalize customer name for matching:

    - Casefold (lowercase)
    - Strip punctuation
    - Collapse multiple whitespace
    - Drop common honorifics
    """
    if not s:
        return ""

    text = s.casefold()
    # Strip punctuation
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()

    # Filter honorifics
    filtered_tokens = [t for t in tokens if t not in HONORIFICS]
    return " ".join(filtered_tokens)


def dedupe_key(
    customer_key: str,
    date: str,
    amount_paise: int,
    entry_type: str,
    desc_norm: str,
) -> str:
    """Generate SHA-1 deduplication hash from normalized transaction fields."""
    raw = f"{customer_key.strip().lower()}|{date.strip()}|{amount_paise}|{entry_type.strip().lower()}|{desc_norm.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def match_customer(
    name_latin: Optional[str],
    name_raw: Optional[str],
    existing_customers: List[Dict[str, Any]],
) -> MatchResult:
    """Match extracted customer name against existing customers using rapidfuzz token_set_ratio.

    Rules:
    - Score >= MATCH_AUTO (92) and margin over 2nd candidate >= MATCH_TIE_MARGIN (5) -> auto
    - Score >= MATCH_SUGGEST (75) or ambiguous tie -> suggest
    - Otherwise -> new
    """
    query_name = name_latin or name_raw or ""
    query_key = normalize_name(query_name)

    if not query_key or not existing_customers:
        return MatchResult(customer_id=None, score=0.0, status="new", candidates=[])

    scored = []
    for c in existing_customers:
        c_key = c.get("name_key") or normalize_name(c.get("display_name", ""))
        score = fuzz.token_set_ratio(query_key, c_key)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_cust = scored[0]

    # Check second candidate for tie-breaking
    second_score = scored[1][0] if len(scored) > 1 else 0

    candidates = [
        {"customer_id": str(c["_id"]), "name": c.get("display_name", ""), "score": s}
        for s, c in scored[:5]
    ]

    is_tied = (top_score - second_score) < MATCH_TIE_MARGIN and top_score >= MATCH_SUGGEST

    if top_score >= MATCH_AUTO and not is_tied:
        return MatchResult(
            customer_id=str(top_cust["_id"]),
            score=float(top_score),
            status="auto",
            candidates=candidates,
        )
    elif top_score >= MATCH_SUGGEST or is_tied:
        return MatchResult(
            customer_id=str(top_cust["_id"]),
            score=float(top_score),
            status="suggest",
            candidates=candidates,
        )
    else:
        return MatchResult(
            customer_id=None,
            score=float(top_score),
            status="new",
            candidates=candidates,
        )


def validate_page(
    page: ExtractedPage,
    today: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Validate extracted entries and flag anomalies.

    Returns:
        (list of validated row dicts with flags, total_mismatch_boolean)
    """
    validated_rows = []
    credit_sum = 0.0

    for entry in page.entries:
        flags = []

        # Confidence flag
        if entry.confidence < CONF_REVIEW_THRESHOLD:
            flags.append("low_confidence")

        # Amount validation
        if entry.amount is None:
            flags.append("missing_amount")
        else:
            if entry.amount <= 0:
                flags.append("non_positive_amount")
            if entry.amount > AMOUNT_OUTLIER_RUPEES:
                flags.append("amount_outlier")

        # Date validation
        if not entry.date and not entry.date_raw:
            flags.append("missing_date")
        elif entry.date:
            try:
                if entry.date > today:
                    flags.append("future_date")
            except Exception:
                pass

        # Entry type
        if entry.entry_type == "unknown":
            flags.append("unknown_type")

        # Customer name
        if not entry.customer_name_raw and not entry.customer_name_latin:
            flags.append("missing_name")

        # Accumulate credit sum for page total verification
        if entry.entry_type == "credit" and entry.amount is not None and entry.amount > 0:
            credit_sum += entry.amount

        validated_rows.append({
            "entry": entry,
            "flags": flags,
        })

    # Page-level total mismatch: stated_page_total vs credit sum
    total_mismatch = False
    if page.stated_page_total is not None and page.stated_page_total > 0:
        if abs(page.stated_page_total - credit_sum) > 0.01:
            total_mismatch = True

    return validated_rows, total_mismatch


def build_review_rows(
    validated_entries: List[Dict[str, Any]],
    existing_customers: List[Dict[str, Any]],
    today: str,
) -> List[ReviewRow]:
    """Construct ReviewRow dataclasses for the editable review panel."""
    review_rows = []

    for item in validated_entries:
        entry: ExtractedEntry = item["entry"]
        flags: List[str] = item["flags"]

        # Rows flagged with low_confidence, unknown_type or missing_amount start unchecked
        critical_flags = {"low_confidence", "unknown_type", "missing_amount", "non_positive_amount"}
        has_critical_issue = any(f in critical_flags for f in flags)
        default_include = not has_critical_issue

        # Customer matching
        raw_name = (entry.customer_name_raw or entry.customer_name_latin or "").strip()
        match = match_customer(entry.customer_name_latin, entry.customer_name_raw, existing_customers)

        if match.status == "auto":
            # Find matching customer's display name
            matched_cust = next(
                (c for c in existing_customers if str(c["_id"]) == match.customer_id),
                None
            )
            customer_selection = matched_cust["display_name"] if matched_cust else (raw_name or "Unknown")
        elif match.status == "suggest" and match.customer_id:
            matched_cust = next(
                (c for c in existing_customers if str(c["_id"]) == match.customer_id),
                None
            )
            customer_selection = matched_cust["display_name"] if matched_cust else f"NEW: {raw_name}"
        else:
            customer_selection = f"NEW: {raw_name}" if raw_name else "NEW: Unknown"

        entry_date = entry.date or entry.date_raw or today
        warning_icon = "⚠️" if flags else "✅"

        review_rows.append(ReviewRow(
            row_number=entry.row_number,
            include=default_include,
            warning=warning_icon,
            date=entry_date,
            customer=customer_selection,
            description=entry.description or "",
            entry_type=entry.entry_type if entry.entry_type in ("credit", "payment") else "credit",
            amount=float(entry.amount or 0.0),
            confidence=round(entry.confidence, 2),
            flags=", ".join(flags) if flags else "clean",
            customer_name_latin=entry.customer_name_latin or "",
            notes=entry.notes or "",
            original_name_raw=entry.customer_name_raw or "",
        ))

    return review_rows


def compute_balances(
    entries: List[Dict[str, Any]],
    customers: List[Dict[str, Any]],
    today: str,
) -> List[CustomerBalance]:
    """Compute per-customer balances and payment aging strictly via deterministic code.

    AI READS. CODE COMPUTES.
    balance_paise = credits - payments.
    """
    customer_map = {str(c["_id"]): c.get("display_name", "Unknown") for c in customers}
    today_dt = datetime.fromisoformat(today) if "-" in today else datetime.now(timezone.utc)

    # Aggregate by customer_id
    stats: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        cust_id = str(entry["customer_id"])
        if cust_id not in stats:
            stats[cust_id] = {
                "balance_paise": 0,
                "latest_date": None,
                "latest_payment_date": None,
                "earliest_credit_date": None,
            }

        amount = entry.get("amount_paise", 0)
        etype = entry.get("entry_type", "credit")
        edate = entry.get("entry_date")

        if etype == "credit":
            stats[cust_id]["balance_paise"] += amount
            if edate:
                if not stats[cust_id]["earliest_credit_date"] or edate < stats[cust_id]["earliest_credit_date"]:
                    stats[cust_id]["earliest_credit_date"] = edate
        elif etype == "payment":
            stats[cust_id]["balance_paise"] -= amount
            if edate:
                if not stats[cust_id]["latest_payment_date"] or edate > stats[cust_id]["latest_payment_date"]:
                    stats[cust_id]["latest_payment_date"] = edate

        if edate:
            if not stats[cust_id]["latest_date"] or edate > stats[cust_id]["latest_date"]:
                stats[cust_id]["latest_date"] = edate

    result = []
    for cust_id, s in stats.items():
        name = customer_map.get(cust_id, "Unknown Customer")
        days_since_payment = None

        ref_date_str = s["latest_payment_date"] or s["earliest_credit_date"]
        if ref_date_str:
            try:
                ref_dt = datetime.fromisoformat(ref_date_str)
                delta = (today_dt.date() if hasattr(today_dt, "date") else today_dt) - (ref_dt.date() if hasattr(ref_dt, "date") else ref_dt)
                days_since_payment = max(0, delta.days)
            except Exception:
                pass

        result.append(CustomerBalance(
            customer_id=cust_id,
            name=name,
            balance_paise=s["balance_paise"],
            last_activity=s["latest_date"],
            last_payment_date=s["latest_payment_date"],
            days_since_payment=days_since_payment,
        ))

    # Sort by balance_paise descending (highest debtors first)
    result.sort(key=lambda cb: cb.balance_paise, reverse=True)
    return result


def build_ledger_context(
    balances: List[CustomerBalance],
    today: str,
) -> str:
    """Generate compact JSON context injected into each chat message."""
    total_outstanding_paise = sum(b.balance_paise for b in balances if b.balance_paise > 0)
    customers_with_dues = sum(1 for b in balances if b.balance_paise > 0)

    top_customers = []
    for b in balances[:25]:
        top_customers.append({
            "name": b.name,
            "balance": format_inr(b.balance_paise),
            "days_since_payment": b.days_since_payment if b.days_since_payment is not None else "no payment recorded",
            "last_activity": b.last_activity or "unknown",
        })

    payload = {
        "as_of_date": today,
        "total_outstanding": format_inr(total_outstanding_paise),
        "total_customers_with_dues": customers_with_dues,
        "customers": top_customers,
    }
    return f"LEDGER_CONTEXT:\n{json.dumps(payload, ensure_ascii=False)}"


def save_reviewed_entries(
    db: Any,
    shop_id: Any,
    page_id: Any,
    rows: List[ReviewRow],
    existing_customers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist confirmed review rows into MongoDB entries collection."""
    cust_name_to_id = {c.get("display_name"): c["_id"] for c in existing_customers}
    entries_to_insert = []
    affected_customers = set()

    for row in rows:
        if not row.include:
            continue

        raw_cust_selection = row.customer.strip()
        if raw_cust_selection.startswith("NEW:"):
            display_name = raw_cust_selection[4:].strip()
            name_key = normalize_name(display_name)
            cust_id = upsert_customer(db, shop_id, display_name, name_key)
        else:
            cust_id = cust_name_to_id.get(raw_cust_selection)
            if not cust_id:
                # Customer not found in map, upsert
                name_key = normalize_name(raw_cust_selection)
                cust_id = upsert_customer(db, shop_id, raw_cust_selection, name_key)

        affected_customers.add(cust_id)
        amount_paise = rupees_to_paise(row.amount)
        cust_key = normalize_name(raw_cust_selection)

        d_key = dedupe_key(
            customer_key=cust_key,
            date=row.date,
            amount_paise=amount_paise,
            entry_type=row.entry_type,
            desc_norm=row.description.strip().lower(),
        )

        entries_to_insert.append({
            "shop_id": shop_id,
            "customer_id": cust_id,
            "page_id": page_id,
            "entry_date": row.date,
            "description": row.description,
            "amount_paise": amount_paise,
            "entry_type": row.entry_type,
            "confidence": row.confidence,
            "flags": [f.strip() for f in row.flags.split(",") if f.strip() and f.strip() != "clean"],
            "dedupe_key": d_key,
        })

    inserted, duplicates = insert_entries(db, shop_id, entries_to_insert)
    if page_id:
        update_page_status(db, page_id, shop_id, "imported")

    return {
        "saved": inserted,
        "duplicates": duplicates,
        "affected_customer_ids": list(affected_customers),
    }
