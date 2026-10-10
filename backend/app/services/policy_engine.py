"""Deterministic expense-policy checks applied to every receipt."""

import re
from datetime import date, timedelta

from app.models.domain import Flag, Receipt
from app.models.policy import Policy

FIELD_LABELS = {
    "vendor": "merchant name",
    "date": "date",
    "total_amount": "total amount",
    "currency": "currency",
    "category": "category",
    "business_purpose": "business purpose",
    "attendees": "attendees",
    "description": "description",
}


def _keyword_in(keyword: str, haystack: str) -> bool:
    """Whole-word match for Latin keywords; plain substring for Indic scripts, where \\b is unreliable."""
    keyword = keyword.strip().lower()
    if keyword.isascii():
        return re.search(rf"\b{re.escape(keyword)}\b", haystack) is not None
    return keyword in haystack


class PolicyEngine:
    def __init__(self, policy: Policy, base_currency: str, low_confidence_threshold: float) -> None:
        self.policy = policy
        self.base_currency = base_currency
        self.low_confidence_threshold = low_confidence_threshold

    # ------------------------------------------------------------ categorise

    def categorise(self, receipt: Receipt, raw_text: str = "") -> str:
        """Keep a specific model-chosen category; otherwise (missing or "other") infer one from keywords."""
        haystack = " ".join(
            filter(
                None,
                [
                    receipt.data.vendor,
                    receipt.data.vendor_local,
                    receipt.data.description,
                    " ".join(i.description for i in receipt.data.line_items),
                    raw_text[:1500],
                    receipt.file_name,
                ],
            )
        ).lower()
        haystack = re.sub(r"[_\-.]+", " ", haystack)

        def excluded(rule) -> bool:
            return any(_keyword_in(word, haystack) for word in rule.excludes)

        chosen = self.policy.category(receipt.data.category)
        if chosen and chosen.key != "other" and not excluded(chosen):
            return chosen.key

        best_key, best_hits = "other", 0
        for rule in self.policy.categories:
            if excluded(rule):
                continue
            hits = sum(1 for kw in rule.keywords if _keyword_in(kw, haystack))
            if hits > best_hits:
                best_key, best_hits = rule.key, hits
        return best_key

    # -------------------------------------------------------------- evaluate

    def evaluate(self, receipt: Receipt) -> None:
        """Populate missing fields, flags and amounts on the receipt in place."""
        data = receipt.data
        flags: list[Flag] = []
        rule = self.policy.category(data.category)

        required = list(self.policy.required_fields)
        if rule:
            required += [f for f in rule.requires if f not in required]
        missing = [f for f in required if not getattr(data, f, None)]

        if receipt.read_warning:
            flags.append(Flag(code="UNREADABLE", severity="warning", message=receipt.read_warning))

        if not receipt.is_receipt:
            flags.append(Flag(code="NOT_A_RECEIPT", severity="error",
                              message="This document doesn't look like a receipt or invoice."))

        expense_date = self._parse_date(data.date)
        if data.date and expense_date is None and "date" not in missing:
            missing.append("date")
        if expense_date:
            today = date.today()
            if expense_date > today:
                flags.append(Flag(code="FUTURE_DATE", severity="error",
                                  message=f"The date {expense_date:%d %b %Y} is in the future."))
            elif (today - expense_date).days > self.policy.max_receipt_age_days:
                severity = "warning" if receipt.justification else "error"
                flags.append(Flag(code="STALE_RECEIPT", severity=severity,
                                  message=f"Older than the {self.policy.max_receipt_age_days}-day submission window."))
            if self.policy.weekend_expenses == "warn" and expense_date.weekday() >= 5:
                flags.append(Flag(code="WEEKEND", severity="info", message="Expense was incurred on a weekend."))

        receipt.amount_in_base = self._to_base(data.total_amount, data.currency)
        if data.currency and data.currency.upper() not in self.policy.fx_rates:
            flags.append(Flag(code="UNKNOWN_CURRENCY", severity="error",
                              message=f"Currency {data.currency} is not supported by policy."))
        elif data.currency and data.currency.upper() != self.base_currency and receipt.amount_in_base:
            flags.append(Flag(code="FOREIGN_CURRENCY", severity="info",
                              message=f"Converted to {self.base_currency} {receipt.amount_in_base:,.2f} at policy rate."))

        reimbursable = receipt.amount_in_base
        blocked = self._blocked_amount(receipt)
        if blocked is not None:
            flags.append(Flag(code="NON_REIMBURSABLE_ITEMS", severity="warning",
                              message="Contains non-reimbursable items (e.g. alcohol/tobacco)"
                                      + ("; they are deducted." if blocked else ".")))
            if reimbursable is not None:
                reimbursable = max(0.0, reimbursable - blocked)

        if rule and rule.limit_per_item and reimbursable is not None and reimbursable > rule.limit_per_item:
            flags.append(Flag(code="OVER_LIMIT", severity="warning",
                              message=f"Exceeds the {rule.label} limit of {self.base_currency} {rule.limit_per_item:,.0f}; "
                                      f"reimbursement is capped."))
            reimbursable = rule.limit_per_item

        if receipt.duplicate_of and not receipt.duplicate_acknowledged:
            flags.append(Flag(code="POSSIBLE_DUPLICATE", severity="warning",
                              message="Looks like a duplicate of another receipt you've uploaded."))

        low = self.low_confidence_fields(receipt)
        if low:
            flags.append(Flag(code="LOW_CONFIDENCE", severity="info",
                              message=f"Low confidence on: {', '.join(FIELD_LABELS.get(f, f) for f in low)}."))

        receipt.missing_fields = missing
        receipt.flags = flags
        receipt.reimbursable_amount = round(reimbursable, 2) if reimbursable is not None else None

    # --------------------------------------------------------------- helpers

    def low_confidence_fields(self, receipt: Receipt) -> list[str]:
        return [
            f for f in ("total_amount", "date", "vendor")
            if getattr(receipt.data, f) is not None
            and receipt.confidence.get(f, 1) < self.low_confidence_threshold
            and f not in receipt.confirmed_fields
        ]

    def needs_justification(self, receipt: Receipt) -> bool:
        return not receipt.justification and any(
            f.code in ("OVER_LIMIT", "STALE_RECEIPT") for f in receipt.flags
        )

    def _to_base(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None:
            return None
        rate = self.policy.fx_rates.get((currency or self.base_currency).upper())
        return round(amount * rate, 2) if rate else None

    def _blocked_amount(self, receipt: Receipt) -> float | None:
        keywords = [k.lower() for k in self.policy.blocked_keywords]
        blocked_items = [
            item for item in receipt.data.line_items
            if any(re.search(rf"\b{re.escape(k)}\b", item.description.lower()) for k in keywords)
        ]
        if blocked_items:
            total = sum(i.amount or 0 for i in blocked_items)
            return self._to_base(total, receipt.data.currency) or 0.0
        text = f"{receipt.data.description or ''} {receipt.data.vendor or ''}".lower()
        return 0.0 if any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords) else None

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    @staticmethod
    def within_days(a: str | None, b: str | None, days: int) -> bool:
        da, db = PolicyEngine._parse_date(a), PolicyEngine._parse_date(b)
        return bool(da and db and abs(da - db) <= timedelta(days=days))
