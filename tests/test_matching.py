"""Unit tests for customer name matching and normalization."""

import pytest
from ledger import match_customer, normalize_name


def test_normalize_name_honorifics_and_punctuation():
    # Strips punctuation, whitespace, and honorifics
    assert normalize_name("Shri Ramesh Kumar Bhai") == "ramesh kumar"
    assert normalize_name("Mr. Suresh Raina, Ji") == "suresh raina"
    assert normalize_name("Anna Venkatesh Garu") == "venkatesh"
    assert normalize_name("Smt. Lakshmi Akka") == "lakshmi"


def test_matching_auto():
    existing = [
        {"_id": "1", "display_name": "Ramesh Kumar", "name_key": "ramesh kumar"},
        {"_id": "2", "display_name": "Suresh Raina", "name_key": "suresh raina"},
    ]
    # Exact or near-exact transliteration match
    res = match_customer("ramesh  kumar", None, existing)
    assert res.status == "auto"
    assert res.customer_id == "1"
    assert res.score >= 92


def test_matching_tie_gives_suggest_never_auto():
    # Ambiguous customer: "Ramesh" vs "Ramesh Kumar" and "Ramesh Gupta"
    # §8.4 & §13 requirement: "Ramesh" vs two Rameshes must be suggest, never auto.
    existing = [
        {"_id": "1", "display_name": "Ramesh Kumar", "name_key": "ramesh kumar"},
        {"_id": "2", "display_name": "Ramesh Gupta", "name_key": "ramesh gupta"},
    ]
    res = match_customer("Ramesh", None, existing)
    assert res.status == "suggest"
    assert len(res.candidates) >= 2


def test_matching_unmatched_gives_new():
    existing = [
        {"_id": "1", "display_name": "Ramesh Kumar", "name_key": "ramesh kumar"},
    ]
    res = match_customer("Suresh Raina", None, existing)
    assert res.status == "new"
    assert res.customer_id is None
