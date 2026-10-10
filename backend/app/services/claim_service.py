"""Claim-level bookkeeping: what is complete, missing or questionable."""

from collections import defaultdict
from datetime import date

from app.models.api import ReceiptUpdate
from app.models.domain import (
    CategoryGroup,
    ChecklistItem,
    Claim,
    ClaimStatus,
    Question,
    Receipt,
    ReceiptStage,
    ReceiptStatus,
)
from app.models.policy import TRAVEL_CATEGORIES, Policy
from app.repositories.claim_repository import ClaimRepository
from app.services.duplicate_detector import DuplicateDetector
from app.services.normalizers import normalise_currency, normalise_date, to_amount
from app.services.policy_engine import PolicyEngine
from app.services.question_engine import QuestionEngine

TERMINAL_STAGES = {ReceiptStage.COMPLETED, ReceiptStage.FAILED}
EXPENSE_FIELDS = set(ReceiptUpdate.model_fields) - {"justification", "excluded"}


class AnswerError(ValueError):
    """Raised when an answer cannot be applied to a question."""


class ClaimService:
    def __init__(
        self,
        policy: Policy,
        engine: PolicyEngine,
        detector: DuplicateDetector,
        questions: QuestionEngine,
        claims: ClaimRepository,
    ) -> None:
        self._policy = policy
        self._engine = engine
        self._detector = detector
        self._questions = questions
        self._claims = claims

    # -------------------------------------------------------------- recompute

    def recompute(self, claim: Claim) -> None:
        """Re-run checks and refresh every derived value on the claim."""
        if not claim.is_editable:
            return

        other_claims = [c for c in self._claims.for_user(claim.user_id) if c.id != claim.id]
        candidates = [r for c in other_claims for r in c.receipts] + claim.receipts
        origin = {r.id: c for c in other_claims for r in c.receipts}
        for receipt in claim.receipts:
            if receipt.stage == ReceiptStage.COMPLETED and not receipt.excluded:
                self._inherit_purpose(claim, receipt)
                self.check_receipt(receipt, candidates)
                receipt.duplicate_note = self._duplicate_note(receipt, origin)

        claim.questions = self._questions.build(claim)
        self._refresh_receipt_statuses(claim)
        self._refresh_totals(claim)
        self._refresh_checklist(claim)
        claim.status = self._derive_status(claim)
        if claim.title_is_auto:
            claim.title = self._auto_title(claim)

    def _inherit_purpose(self, claim: Claim, receipt: Receipt) -> None:
        """Receipts whose category needs a business purpose reuse the claim's remarks,
        unless the employee wrote one for that receipt."""
        rule = self._policy.category(receipt.data.category)
        needs = bool(rule and "business_purpose" in rule.requires)
        if receipt.purpose_inherited and (not needs or not claim.purpose):
            receipt.data.business_purpose, receipt.purpose_inherited = None, False
        elif needs and claim.purpose and (receipt.purpose_inherited or not receipt.data.business_purpose):
            receipt.data.business_purpose, receipt.purpose_inherited = claim.purpose, True

    def check_receipt(self, receipt: Receipt, candidates: list[Receipt]) -> None:
        previous = receipt.duplicate_of
        receipt.duplicate_of = self._detector.find(receipt, candidates)
        if receipt.duplicate_of != previous:
            receipt.duplicate_acknowledged = False
        self._engine.evaluate(receipt)

    @staticmethod
    def _duplicate_note(receipt: Receipt, origin: dict[str, Claim]) -> str | None:
        if not receipt.duplicate_of:
            return None
        source = origin.get(receipt.duplicate_of)
        if source is None:
            return "in this claim"
        label = f"“{source.title}”" + (f" ({source.reference_no})" if source.reference_no else "")
        return f"in your claim {label}"

    def _refresh_receipt_statuses(self, claim: Claim) -> None:
        with_questions = {q.receipt_id for q in claim.questions}
        for r in claim.receipts:
            if r.excluded:
                r.status = ReceiptStatus.EXCLUDED
            elif r.stage == ReceiptStage.FAILED:
                r.status = ReceiptStatus.FAILED
            elif r.stage != ReceiptStage.COMPLETED:
                r.status = ReceiptStatus.PROCESSING
            elif r.missing_fields:
                r.status = ReceiptStatus.NEEDS_INFO
            elif r.id in with_questions or any(f.severity == "error" for f in r.flags):
                r.status = ReceiptStatus.QUESTIONABLE
            else:
                r.status = ReceiptStatus.COMPLETE

    def _refresh_totals(self, claim: Claim) -> None:
        done = [r for r in claim.active_receipts if r.stage == ReceiptStage.COMPLETED]
        claim.total_claimed = round(sum(r.amount_in_base or 0 for r in done), 2)
        claim.total_reimbursable = round(sum(r.reimbursable_amount or 0 for r in done), 2)

        grouped: dict[str, list[Receipt]] = defaultdict(list)
        for r in done:
            grouped[r.data.category or "other"].append(r)
        claim.groups = []
        for key, items in sorted(grouped.items(), key=lambda kv: -sum(r.amount_in_base or 0 for r in kv[1])):
            rule = self._policy.category(key)
            claim.groups.append(
                CategoryGroup(
                    category=key,
                    label=rule.label if rule else key.title(),
                    icon=rule.icon if rule else "🧾",
                    count=len(items),
                    total=round(sum(r.amount_in_base or 0 for r in items), 2),
                )
            )

        dates = sorted(r.data.date for r in done if r.data.date)
        claim.period_start = dates[0] if dates else None
        claim.period_end = dates[-1] if dates else None

    def _refresh_checklist(self, claim: Claim) -> None:
        active = claim.active_receipts
        any_active = bool(active)
        claim.checklist = [
            ChecklistItem(key="uploaded", label="Receipts uploaded", done=any_active),
            ChecklistItem(
                key="processed", label="All receipts read by the agent",
                done=any_active and all(r.stage == ReceiptStage.COMPLETED for r in active),
            ),
            ChecklistItem(
                key="details", label="Required details captured",
                done=any_active and not any(r.missing_fields for r in active),
            ),
            ChecklistItem(
                key="policy", label="Policy checks passed",
                done=any_active and not any(
                    any(f.severity == "error" for f in r.flags) or self._engine.needs_justification(r)
                    for r in active
                ),
            ),
            ChecklistItem(
                key="duplicates", label="No unresolved duplicates",
                done=any_active and not any(r.duplicate_of and not r.duplicate_acknowledged for r in active),
            ),
            ChecklistItem(
                key="purpose", label="Purpose / remarks added",
                done=bool(claim.purpose) or not self._policy.claim_requires_purpose,
            ),
        ]
        claim.readiness = round(100 * sum(i.done for i in claim.checklist) / len(claim.checklist))

    def _derive_status(self, claim: Claim) -> ClaimStatus:
        active = claim.active_receipts
        if not active:
            return ClaimStatus.DRAFT
        if any(r.stage not in TERMINAL_STAGES for r in active):
            return ClaimStatus.PROCESSING
        if claim.questions or not all(i.done for i in claim.checklist):
            return ClaimStatus.NEEDS_ATTENTION
        return ClaimStatus.READY

    def _auto_title(self, claim: Claim) -> str:
        if not claim.period_start:
            return "New expense claim"
        start = date.fromisoformat(claim.period_start)
        end = date.fromisoformat(claim.period_end or claim.period_start)
        if start == end:
            period = f"{start:%d %b %Y}"
        elif (start.year, start.month) == (end.year, end.month):
            period = f"{start.day}–{end:%d %b %Y}"
        else:
            period = f"{start:%d %b} – {end:%d %b %Y}"

        cities = [r.data.location for r in claim.active_receipts if r.data.location]
        has_travel = any(r.data.category in TRAVEL_CATEGORIES for r in claim.active_receipts)
        if has_travel and cities:
            return f"{max(set(cities), key=cities.count).title()} trip · {period}"
        return f"Expenses · {period}"

    # ---------------------------------------------------------------- answers

    def apply_answer(self, claim: Claim, question: Question, answer) -> str:
        """Apply an answer and return a human-readable echo of it."""
        if question.kind == "purpose":
            self.set_purpose(claim, self._require_text(answer))
            return claim.purpose

        receipt = claim.receipt(question.receipt_id or "")
        if receipt is None:
            raise AnswerError("This receipt no longer exists")

        if question.kind in ("duplicate", "not_receipt"):
            if answer not in ("exclude", "keep"):
                raise AnswerError("Choose one of the options")
            if answer == "exclude":
                receipt.excluded = True
            elif question.kind == "duplicate":
                receipt.duplicate_acknowledged = True
            else:
                receipt.is_receipt = True
            return next(o["label"] for o in question.options if o["value"] == answer)

        if question.kind == "justification":
            receipt.justification = self._require_text(answer)
            return receipt.justification

        field = "total_amount" if question.kind == "confirm_amount" else question.kind
        self.set_field(receipt, field, answer)
        value = getattr(receipt.data, field)
        return f"{value:,.2f}" if isinstance(value, float) else str(value)

    def set_purpose(self, claim: Claim, text, source: str = "user") -> None:
        """Set the claim's purpose/remarks; a user-written purpose is never overwritten by the agent."""
        value = str(text or "").strip()[:500] or None
        if source == "user":
            claim.purpose, claim.purpose_source = value, "user" if value else None
        elif claim.purpose_source != "user":
            claim.purpose, claim.purpose_source = value, "agent" if value else None

    def apply_update(self, receipt: Receipt, update: ReceiptUpdate) -> None:
        changes = update.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if field == "excluded":
                receipt.excluded = bool(value)
            elif field == "justification":
                receipt.justification = value or None
            elif field in EXPENSE_FIELDS:
                self.set_field(receipt, field, value)
        if changes.keys() & EXPENSE_FIELDS:
            receipt.read_warning = None  # the employee filled the details in themselves
        if receipt.stage == ReceiptStage.FAILED and changes.keys() & EXPENSE_FIELDS:
            receipt.stage, receipt.progress, receipt.error = ReceiptStage.COMPLETED, 100, None
            receipt.extraction_source = "manual"

    def set_field(self, receipt: Receipt, field: str, value) -> None:
        if field not in EXPENSE_FIELDS:
            raise AnswerError(f"Unknown field {field}")
        if field in ("total_amount", "tax_amount"):
            value = to_amount(value)
            if value is None or value < 0:
                raise AnswerError("Please enter a valid amount")
        elif field == "date":
            value = normalise_date(value)
            if value is None:
                raise AnswerError("Please enter a valid date (YYYY-MM-DD)")
        elif field == "currency":
            value = normalise_currency(value)
            if value not in self._policy.fx_rates:
                raise AnswerError("Unsupported currency")
        elif field == "category":
            if not self._policy.category(value):
                raise AnswerError("Unknown category")
        else:
            value = self._require_text(value)

        setattr(receipt.data, field, value)
        if field == "business_purpose":
            receipt.purpose_inherited = False
        receipt.confidence[field] = 1.0
        if field not in receipt.confirmed_fields:
            receipt.confirmed_fields.append(field)

    @staticmethod
    def _require_text(value) -> str:
        text = str(value or "").strip()
        if not text:
            raise AnswerError("Please type an answer")
        return text[:500]
