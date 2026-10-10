from difflib import SequenceMatcher

from app.models.domain import Receipt, ReceiptStage
from app.models.policy import DuplicateRule
from app.services.policy_engine import PolicyEngine


class DuplicateDetector:
    def __init__(self, rule: DuplicateRule) -> None:
        self._rule = rule

    def find(self, receipt: Receipt, candidates: list[Receipt]) -> str | None:
        """Return the id of an earlier receipt this one duplicates, if any.

        Only receipts uploaded *before* this one are considered, so the first
        copy is treated as the original and only later copies get flagged.
        """
        for other in candidates:
            if other.id == receipt.id or other.excluded or not self._is_earlier(other, receipt):
                continue
            if other.sha256 == receipt.sha256:
                return other.id
            if other.stage == ReceiptStage.COMPLETED and self._looks_same(receipt, other):
                return other.id
        return None

    @staticmethod
    def _is_earlier(a: Receipt, b: Receipt) -> bool:
        return (a.uploaded_at, a.id) < (b.uploaded_at, b.id)

    def _looks_same(self, a: Receipt, b: Receipt) -> bool:
        if a.amount_in_base is None or b.amount_in_base is None:
            return False
        if abs(a.amount_in_base - b.amount_in_base) > self._rule.amount_tolerance:
            return False
        if not PolicyEngine.within_days(a.data.date, b.data.date, self._rule.date_window_days):
            return False
        if a.data.invoice_number and a.data.invoice_number == b.data.invoice_number:
            return True
        vendor_a, vendor_b = (a.data.vendor or "").lower(), (b.data.vendor or "").lower()
        return SequenceMatcher(None, vendor_a, vendor_b).ratio() >= self._rule.vendor_similarity
