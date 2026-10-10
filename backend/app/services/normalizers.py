"""Helpers that coerce loosely-typed model output into clean values."""

import json
import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in a model response (tolerates code fences)."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Model returned invalid JSON: %s", cleaned[:300])
    return {}


def clean_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "n/a", "unknown"} else None


# Devanagari, Bengali, Gujarati, Gurmukhi, Tamil, Telugu, Kannada and Malayalam digits -> ASCII.
_INDIC_DIGITS = str.maketrans(
    "०१२३४५६७८९০১২৩৪৫৬৭৮৯૦૧૨૩૪૫૬૭૮૯੦੧੨੩੪੫੬੭੮੯௦௧௨௩௪௫௬௭௮௯౦౧౨౩౪౫౬౭౮౯೦೧೨೩೪೫೬೭೮೯൦൧൨൩൪൫൬൭൮൯",
    "0123456789" * 8,
)

DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d %b %y", "%b %d, %Y", "%B %d, %Y",
)


def ascii_digits(text: str) -> str:
    return text.translate(_INDIC_DIGITS)


def to_amount(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", ascii_digits(str(value)))
    return round(float(match.group().replace(",", "")), 2) if match else None


def normalise_currency(value) -> str | None:
    text = clean_str(value)
    if not text:
        return None
    symbols = {"₹": "INR", "RS": "INR", "RS.": "INR", "RUPEES": "INR", "रु": "INR", "रु.": "INR",
               "$": "USD", "€": "EUR", "£": "GBP"}
    upper = text.upper()
    return symbols.get(upper, upper[:3] if upper.isascii() and upper.isalpha() else None)


def normalise_date(value) -> str | None:
    """Parse ISO dates and day-first formats (Indian bills), including Indic digits."""
    text = clean_str(value)
    if not text:
        return None
    text = ascii_digits(text).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalise_reference(value) -> str | None:
    """Bill / memo numbers: Indic digits to ASCII, and drop spaces inside pure numbers ("0 14821")."""
    text = clean_str(value)
    if not text:
        return None
    text = ascii_digits(text)
    return re.sub(r"\s+", "", text) if re.fullmatch(r"[\d\s/-]+", text) else text


def has_non_latin_letters(text: str | None) -> bool:
    return bool(text) and any(ch.isalpha() and ord(ch) > 0x024F for ch in text)
