"""Deterministic sanity checks on an extraction.

The issues found here are fed back to the model in a verification pass, and any
that remain afterwards lower the confidence of the affected fields.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.domain import ExpenseData
from app.services.normalizers import has_non_latin_letters


@dataclass(frozen=True)
class Issue:
    field: str  # the field whose confidence should drop if the issue persists
    message: str  # written as an instruction for the verifying model


def amounts_close(a: float, b: float, tolerance: float = 0.02) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * tolerance)


def find_issues(data: ExpenseData, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    if not data.vendor:
        issues.append(Issue("vendor", "Merchant name is missing - it is usually the largest text at the top."))
    elif has_non_latin_letters(data.vendor):
        issues.append(Issue("vendor", f"Merchant '{data.vendor}' must be transliterated to English letters; "
                                      "put the original script in vendor_local."))

    if data.total_amount is None:
        issues.append(Issue("total_amount", "Total is missing - look for Total / Grand Total / Net Amount / "
                                            "एकूण / कुल / योग next to the final figure."))

    if not data.date:
        issues.append(Issue("date", "Date is missing - look for Date / Dt. / ता. / दिनांक (day comes first)."))
    else:
        try:
            parsed = date.fromisoformat(data.date)
            if parsed > today or parsed < today - timedelta(days=730):
                issues.append(Issue("date", f"Date {data.date} looks wrong - Indian bills are day-first "
                                            "(dd/mm/yy); re-read each digit."))
        except ValueError:
            issues.append(Issue("date", f"Date '{data.date}' is not a valid date."))

    amounts = [i.amount for i in data.line_items if i.amount is not None]
    totals_agree = False
    if amounts and data.total_amount is not None:
        line_sum = sum(amounts)
        # Line items may or may not already include the tax lines.
        totals_agree = amounts_close(line_sum, data.total_amount) or amounts_close(line_sum + (data.tax_amount or 0), data.total_amount)
        if not totals_agree:
            issues.append(Issue("total_amount",
                f"Line items add up to {line_sum:.2f} but the total is {data.total_amount:.2f}. Only rows "
                "that actually contain handwritten/printed values are line items; quantity and rate are not amounts."))
        if any(a > data.total_amount * 1.01 for a in amounts):
            issues.append(Issue("total_amount", "A line item is larger than the total - re-check both."))

    # When the rows already add up to the total, a quantity/rate slip doesn't put the total in doubt.
    if not totals_agree:
        for item in data.line_items:
            if item.quantity and item.unit_price and item.amount is not None:
                expected = item.quantity * item.unit_price
                if not amounts_close(expected, item.amount):
                    issues.append(Issue("total_amount",
                        f"Line '{item.description}': {item.quantity} × {item.unit_price} = {expected:.2f}, but its "
                        f"amount is {item.amount}. Quantity, rate and amount may have been read from the wrong "
                        "columns or rows."))

    if data.location and (":" in data.location or len(data.location) > 40 or has_non_latin_letters(data.location)
                          or any(ch.isdigit() for ch in data.location)):
        issues.append(Issue("location", f"City '{data.location}' looks wrong - give only the city/area from "
                                        "the address, in English."))

    for item in data.line_items:
        if has_non_latin_letters(item.description):
            issues.append(Issue("description", "Translate every line-item description to English."))
            break

    return issues
