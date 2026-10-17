"""Shared validation primitives.

These are plain functions (not tied to Pydantic) so they can be reused by both
the Pydantic schemas (app/schemas.py) and anything else that needs to
normalize/validate a raw value coming out of a voice conversation, where
input is messy by nature (e.g. "five five five, one two three, four five six
seven" transcribed as "555 123 4567").
"""

import re
from datetime import date, datetime

US_STATES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR", "GU", "VI", "AS", "MP",
    }
)

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

_DOB_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")

MIN_BIRTH_YEAR_OFFSET = 120  # sanity bound: nobody registering is older than this


def validate_name(value: str, field_label: str = "name") -> str:
    if value is None:
        raise ValueError(f"{field_label} is required")
    value = value.strip()
    if not (1 <= len(value) <= 50):
        raise ValueError(f"{field_label} must be between 1 and 50 characters")
    if not _NAME_RE.match(value):
        raise ValueError(f"{field_label} may only contain letters, hyphens, and apostrophes")
    return value


def normalize_phone(raw: str) -> str:
    if raw is None:
        raise ValueError("phone number is required")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("phone number must be a valid U.S. 10-digit number")
    return digits


def validate_zip(raw: str) -> str:
    if raw is None:
        raise ValueError("zip_code is required")
    raw = raw.strip()
    if not _ZIP_RE.match(raw):
        raise ValueError("zip_code must be a 5-digit or ZIP+4 U.S. format (e.g. 94107 or 94107-1234)")
    return raw


def validate_state(raw: str) -> str:
    if raw is None:
        raise ValueError("state is required")
    value = raw.strip().upper()
    if value not in US_STATES:
        raise ValueError("state must be a valid 2-letter U.S. state abbreviation")
    return value


def parse_dob(raw) -> date:
    if raw is None:
        raise ValueError("date_of_birth is required")
    if isinstance(raw, datetime):
        parsed = raw.date()
    elif isinstance(raw, date):
        parsed = raw
    else:
        raw = str(raw).strip()
        parsed = None
        for fmt in _DOB_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("date_of_birth must be a valid date (e.g. 1990-05-14 or 05/14/1990)")

    today = date.today()
    if parsed > today:
        raise ValueError("date_of_birth cannot be in the future")
    if parsed.year < today.year - MIN_BIRTH_YEAR_OFFSET:
        raise ValueError("date_of_birth does not look valid (too far in the past)")
    return parsed
