"""Pydantic schemas and dataclasses for KhataScan."""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field


class ExtractedEntry(BaseModel):
    """Single row extracted from a handwritten khata ledger page."""
    row_number: int
    date_raw: Optional[str] = None
    date: Optional[str] = None                 # ISO YYYY-MM-DD if confident
    customer_name_raw: Optional[str] = None    # as written, any script
    customer_name_latin: Optional[str] = None  # Latin transliteration for matching
    description: Optional[str] = None
    amount: Optional[float] = None             # amount in rupees
    entry_type: Literal["credit", "payment", "unknown"] = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None


class ExtractedPage(BaseModel):
    """Full extraction result from Gemini vision model for a ledger page."""
    is_ledger_page: bool
    image_quality: Literal["good", "fair", "poor"]
    language_hint: Optional[str] = None
    page_date: Optional[str] = None
    stated_page_total: Optional[float] = None
    entries: List[ExtractedEntry] = Field(default_factory=list)
    unreadable_notes: Optional[str] = None


def rupees_to_paise(x: Optional[float]) -> int:
    """Convert amount in rupees (float/int) to integer paise using round half-up."""
    if x is None:
        return 0
    d = Decimal(str(x)) * Decimal("100")
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_inr(paise: int) -> str:
    """Format integer paise into standard Indian Rupee string (e.g. ₹1,250.00)."""
    is_negative = paise < 0
    abs_paise = abs(paise)
    rupees = abs_paise // 100
    fraction = abs_paise % 100

    s = str(rupees)
    if len(s) <= 3:
        formatted_rupees = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted_rupees = ",".join(groups) + "," + last3

    result = f"₹{formatted_rupees}.{fraction:02d}"
    return f"-{result}" if is_negative else result


@dataclass
class ReviewRow:
    """Row structure for Streamlit data editor during human-in-the-loop review."""
    row_number: int
    include: bool
    warning: str
    date: str
    customer: str
    description: str
    entry_type: str
    amount: float
    confidence: float
    flags: str
    customer_name_latin: str = ""
    notes: str = ""
    original_name_raw: str = ""


@dataclass
class MatchResult:
    """Customer matching outcome."""
    customer_id: Optional[str]
    score: float
    status: Literal["auto", "suggest", "new"]
    candidates: List[dict] = field(default_factory=list)


@dataclass
class CustomerBalance:
    """Computed balance and aging facts for a customer."""
    customer_id: str
    name: str
    balance_paise: int
    last_activity: Optional[str] = None
    last_payment_date: Optional[str] = None
    days_since_payment: Optional[int] = None
