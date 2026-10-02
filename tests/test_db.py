"""Unit tests for db.py helpers and tenant isolation."""

from unittest.mock import MagicMock
from pymongo.errors import DuplicateKeyError
import pytest
from db import (
    ensure_indexes,
    create_shop,
    get_shop_by_whatsapp,
    upsert_customer,
    insert_entries,
    delete_all_shop_data,
)


def test_ensure_indexes_calls():
    mock_db = MagicMock()
    ensure_indexes(mock_db)

    # Verify index creation was invoked on all 5 collections
    assert mock_db.shops.create_index.called
    assert mock_db.customers.create_index.called
    assert mock_db.pages.create_index.called
    assert mock_db.entries.create_index.called
    assert mock_db.sends.create_index.called


def test_create_and_get_shop():
    mock_db = MagicMock()
    mock_db.shops.insert_one.return_value.inserted_id = "test_shop_id_123"

    shop = create_shop(
        mock_db,
        whatsapp="+919876543210",
        shop_name="Kiran General Store",
        owner_name="Kiran Kumar",
        pin_hash="fakehash",
        pin_salt="fakesalt",
    )

    assert shop["_id"] == "test_shop_id_123"
    assert shop["shop_name"] == "Kiran General Store"
    mock_db.shops.insert_one.assert_called_once()

    # Test retrieval
    mock_db.shops.find_one.return_value = shop
    retrieved = get_shop_by_whatsapp(mock_db, "+919876543210")
    assert retrieved == shop
    mock_db.shops.find_one.assert_called_with({"whatsapp": "+919876543210"})


def test_insert_entries_duplicate_handling():
    mock_db = MagicMock()

    # Simulate second entry causing DuplicateKeyError
    def mock_insert(doc):
        if doc.get("dedupe_key") == "dup_key":
            raise DuplicateKeyError("E11000 duplicate key error")
        return MagicMock(inserted_id="entry_id")

    mock_db.entries.insert_one.side_effect = mock_insert

    entries = [
        {"dedupe_key": "unique_1", "amount_paise": 1000},
        {"dedupe_key": "dup_key", "amount_paise": 2000},
        {"dedupe_key": "unique_2", "amount_paise": 3000},
    ]

    inserted, duplicates = insert_entries(mock_db, "shop_1", entries)
    assert inserted == 2
    assert duplicates == 1


def test_delete_all_shop_data_isolation():
    mock_db = MagicMock()
    mock_db.entries.delete_many.return_value.deleted_count = 5
    mock_db.pages.delete_many.return_value.deleted_count = 2
    mock_db.customers.delete_many.return_value.deleted_count = 3
    mock_db.sends.delete_many.return_value.deleted_count = 1
    mock_db.shops.delete_many.return_value.deleted_count = 1

    counts = delete_all_shop_data(mock_db, "shop_123")

    mock_db.entries.delete_many.assert_called_with({"shop_id": "shop_123"})
    mock_db.pages.delete_many.assert_called_with({"shop_id": "shop_123"})
    mock_db.customers.delete_many.assert_called_with({"shop_id": "shop_123"})
    mock_db.sends.delete_many.assert_called_with({"shop_id": "shop_123"})
    mock_db.shops.delete_many.assert_called_with({"_id": "shop_123"})

    assert counts["entries"] == 5
    assert counts["shops"] == 1
