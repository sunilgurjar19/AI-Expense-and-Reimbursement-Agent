"""Deterministic receipt parsing from a PDF text layer.

Used by the offline mock provider, and to fill gaps when an LLM misses fields.
"""

import re
from datetime import datetime

# Checked in order. "S$" must come before the bare "$" (but not match inside "US$").
CURRENCY_HINTS = [
    (r"₹|\bRs\.?|\bINR\b", "INR"),
    (r"\bSGD\b|(?<![A-Za-z])S\$", "SGD"),
    (r"\$|\bUSD\b", "USD"),
    (r"€|\bEUR\b", "EUR"),
    (r"£|\bGBP\b", "GBP"),
    (r"\bAED\b|\bDhs?\b", "AED"),
]

DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%d %b, %Y",
]
DATE_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}[ -][A-Za-z]{3,9},?[ -]\d{4}"
    r"|[A-Za-z]{3,9} \d{1,2}, \d{4})\b"
)
# Thousands-separated (1,848.00 / 1,17,882) only when a separator is present, otherwise any run of digits,
# so an unanchored findall reads "1848.00" whole instead of stopping after three digits.
AMOUNT = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
TOTAL_LABELS = r"(grand total|total amount|amount paid|net payable|total payable|amount due|total)"


def to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def find_date(text: str) -> str | None:
    for match in DATE_PATTERN.finditer(text):
        raw = match.group(1).replace(",", ", ").replace(",  ", ", ")
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(raw.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _find_total(text: str) -> float | None:
    for line in text.splitlines():
        if re.search(TOTAL_LABELS, line, re.I) and not re.search(r"sub\s*total", line, re.I):
            amounts = [to_float(a) for a in re.findall(AMOUNT, line)]
            amounts = [a for a in amounts if a is not None]
            if amounts:
                return max(amounts)
    return None


def _find_tax(text: str) -> float | None:
    total = 0.0
    for line in text.splitlines():
        if re.search(r"\b(c?gst|sgst|igst|vat|tax)\b", line, re.I):
            amounts = [to_float(a) for a in re.findall(AMOUNT, line)]
            amounts = [a for a in amounts if a is not None and a < 1_000_000]
            if amounts:
                total += amounts[-1]
    return round(total, 2) or None


def _find_line_items(lines: list[str]) -> list[dict]:
    """Lines shaped like "<description>   <amount>" that aren't totals or taxes."""
    items = []
    skip = re.compile(rf"{TOTAL_LABELS}|sub\s*total|gst|vat|tax|fee|invoice|bill|date", re.I)
    for line in lines[1:]:
        match = re.match(rf"^(.*?[A-Za-z].*?)\s{{2,}}(?:Rs\.?|₹|INR)?\s*{AMOUNT}$", line)
        if match and not skip.search(match.group(1)):
            items.append({"description": match.group(1).strip(), "amount": to_float(match.group(2))})
    return items


def _find(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.I | re.M)
    return match.group(1).strip() if match else None


def extract_with_rules(text: str) -> dict:
    """Regex extraction from a document's text layer (no model needed)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {
            "is_receipt": True,
            "fields": {},
            "confidence": {},
            "notes": "No text layer found - details need to be confirmed manually.",
        }

    currency = next((code for pat, code in CURRENCY_HINTS if re.search(pat, text)), None)
    fields = {
        "vendor": lines[0][:80],
        "date": find_date(text),
        "total_amount": _find_total(text),
        "currency": currency,
        "tax_amount": _find_tax(text),
        "invoice_number": _find(r"(?:invoice|bill|receipt|order)\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9/-]{3,})", text),
        "payment_method": _find(r"(?:paid (?:by|via)|payment (?:mode|method))\s*[:\-]?\s*([A-Za-z ]{3,20})", text),
        "location": _find(r"(?:city|location)\s*[:\-]\s*([A-Za-z ]{3,30})", text),
        "description": None,
        "category": None,
    }
    confidence = {k: (0.7 if v is not None else 0.0) for k, v in fields.items()}
    if fields["total_amount"] is not None:
        confidence["total_amount"] = 0.85
    return {
        "is_receipt": bool(fields["total_amount"] or fields["date"]),
        "fields": fields,
        "confidence": confidence,
        "line_items": _find_line_items(lines),
        "notes": "Extracted with the offline rules engine.",
    }
