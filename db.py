"""MongoDB client, collection indexing, and CRUD helpers for KhataScan.

Every collection query except shops MUST be filtered by shop_id for tenant isolation.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import certifi
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
import streamlit as st

from config import get_secret


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@st.cache_resource
def get_db(uri: Optional[str] = None, db_name: Optional[str] = None):
    """Obtain cached MongoDB database connection and ensure indexes."""
    mongo_uri = uri or get_secret("MONGODB_URI")
    database_name = db_name or get_secret("MONGODB_DB", "khatascan")

    if not mongo_uri:
        raise ConnectionError("MONGODB_URI is not configured in .streamlit/secrets.toml")

    client = MongoClient(
        mongo_uri,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=8000,
    )
    db = client[database_name]
    ensure_indexes(db)
    return db


def ensure_indexes(db: Any) -> None:
    """Create required MongoDB indexes idempotently per spec.md §6."""
    # shops: unique whatsapp
    db.shops.create_index([("whatsapp", ASCENDING)], unique=True)

    # customers: unique (shop_id, name_key)
    db.customers.create_index(
        [("shop_id", ASCENDING), ("name_key", ASCENDING)],
        unique=True,
    )

    # pages: (shop_id, image_sha256)
    db.pages.create_index([("shop_id", ASCENDING), ("image_sha256", ASCENDING)])

    # entries: unique (shop_id, dedupe_key) and (shop_id, customer_id)
    db.entries.create_index(
        [("shop_id", ASCENDING), ("dedupe_key", ASCENDING)],
        unique=True,
    )
    db.entries.create_index([("shop_id", ASCENDING), ("customer_id", ASCENDING)])

    # sends: (shop_id, created_at)
    db.sends.create_index([("shop_id", ASCENDING), ("created_at", ASCENDING)])


# ---------------------------------------------------------
# Shop Helpers
# ---------------------------------------------------------

def create_shop(
    db: Any,
    whatsapp: str,
    shop_name: str,
    owner_name: str,
    pin_hash: str,
    pin_salt: str,
    language: str = "English",
) -> Dict[str, Any]:
    """Create a new shop account."""
    shop_doc = {
        "whatsapp": whatsapp,
        "shop_name": shop_name,
        "owner_name": owner_name,
        "pin_hash": pin_hash,
        "pin_salt": pin_salt,
        "language": language,
        "created_at": _now_iso(),
    }
    result = db.shops.insert_one(shop_doc)
    shop_doc["_id"] = result.inserted_id
    return shop_doc


def get_shop_by_whatsapp(db: Any, whatsapp: str) -> Optional[Dict[str, Any]]:
    """Retrieve shop by WhatsApp number (unique)."""
    return db.shops.find_one({"whatsapp": whatsapp})


def get_shop_by_id(db: Any, shop_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieve shop by MongoDB _id."""
    return db.shops.find_one({"_id": shop_id})


# ---------------------------------------------------------
# Customer Helpers
# ---------------------------------------------------------

def upsert_customer(
    db: Any,
    shop_id: Any,
    display_name: str,
    name_key: str,
    phone: Optional[str] = None,
) -> Any:
    """Upsert customer scoped by shop_id and return customer _id."""
    update_doc: Dict[str, Any] = {
        "$set": {"display_name": display_name},
        "$setOnInsert": {
            "shop_id": shop_id,
            "name_key": name_key,
            "created_at": _now_iso(),
        },
    }
    if phone:
        update_doc["$set"]["phone"] = phone

    result = db.customers.find_one_and_update(
        {"shop_id": shop_id, "name_key": name_key},
        update_doc,
        upsert=True,
        return_document=True,
    )
    if result:
        return result["_id"]

    # Fallback lookup
    doc = db.customers.find_one({"shop_id": shop_id, "name_key": name_key})
    return doc["_id"] if doc else None


def update_customer_phone(db: Any, shop_id: Any, customer_id: Any, phone: str) -> None:
    """Update a customer's phone number."""
    db.customers.update_one(
        {"_id": customer_id, "shop_id": shop_id},
        {"$set": {"phone": phone}},
    )


def list_customers(db: Any, shop_id: Any) -> List[Dict[str, Any]]:
    """List all customers for a given shop."""
    return list(db.customers.find({"shop_id": shop_id}))


# ---------------------------------------------------------
# Page Helpers
# ---------------------------------------------------------

def insert_page(
    db: Any,
    shop_id: Any,
    image_sha256: str,
    extraction: Dict[str, Any],
    model_name: str,
    prompt_version: str,
    status: str = "pending",
) -> Any:
    """Insert ledger page record."""
    page_doc = {
        "shop_id": shop_id,
        "image_sha256": image_sha256,
        "status": status,
        "extraction": extraction,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "uploaded_at": _now_iso(),
    }
    result = db.pages.insert_one(page_doc)
    return result.inserted_id


def get_page_by_hash(db: Any, shop_id: Any, image_sha256: str) -> Optional[Dict[str, Any]]:
    """Check if page with given image SHA256 was already uploaded for this shop."""
    return db.pages.find_one({"shop_id": shop_id, "image_sha256": image_sha256})


def update_page_status(db: Any, page_id: Any, shop_id: Any, status: str) -> None:
    """Update page status (e.g. pending -> imported / discarded)."""
    db.pages.update_one(
        {"_id": page_id, "shop_id": shop_id},
        {"$set": {"status": status}},
    )


# ---------------------------------------------------------
# Entry Helpers
# ---------------------------------------------------------

def insert_entries(
    db: Any,
    shop_id: Any,
    entries_docs: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """Insert ledger entries, skipping duplicates on dedupe_key.

    Returns:
        (inserted_count, duplicate_count)
    """
    inserted = 0
    duplicates = 0

    for doc in entries_docs:
        doc_to_save = dict(doc)
        doc_to_save["shop_id"] = shop_id
        if "created_at" not in doc_to_save:
            doc_to_save["created_at"] = _now_iso()
        try:
            db.entries.insert_one(doc_to_save)
            inserted += 1
        except DuplicateKeyError:
            duplicates += 1

    return inserted, duplicates


def list_entries(
    db: Any,
    shop_id: Any,
    customer_id: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """List ledger entries scoped by shop_id, optionally filtered by customer_id."""
    query: Dict[str, Any] = {"shop_id": shop_id}
    if customer_id is not None:
        query["customer_id"] = customer_id
    return list(db.entries.find(query).sort("entry_date", ASCENDING))


# ---------------------------------------------------------
# Audit & Send Logging
# ---------------------------------------------------------

def log_send(
    db: Any,
    shop_id: Any,
    kind: str,
    twilio_sid: Optional[str],
    ok: bool,
    info: str,
) -> Any:
    """Log an outbound message transmission."""
    send_doc = {
        "shop_id": shop_id,
        "kind": kind,
        "twilio_sid": twilio_sid,
        "ok": ok,
        "info": info,
        "created_at": _now_iso(),
    }
    result = db.sends.insert_one(send_doc)
    return result.inserted_id


# ---------------------------------------------------------
# Privacy: Delete My Data
# ---------------------------------------------------------

def delete_all_shop_data(db: Any, shop_id: Any) -> Dict[str, int]:
    """Permanently delete all documents belonging to a shop (Privacy requirement)."""
    counts = {
        "entries": db.entries.delete_many({"shop_id": shop_id}).deleted_count,
        "pages": db.pages.delete_many({"shop_id": shop_id}).deleted_count,
        "customers": db.customers.delete_many({"shop_id": shop_id}).deleted_count,
        "sends": db.sends.delete_many({"shop_id": shop_id}).deleted_count,
        "shops": db.shops.delete_many({"_id": shop_id}).deleted_count,
    }
    return counts
