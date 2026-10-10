"""Decides the *minimum* set of questions needed to make a claim submittable."""

from app.models.domain import Claim, Question, Receipt, ReceiptStage
from app.models.policy import Policy
from app.services.policy_engine import PolicyEngine

FIELD_TYPES = {"date": "date", "total_amount": "number", "currency": "select", "category": "select"}

FIELD_PROMPTS = {
    "vendor": "Who was the merchant on {name}?",
    "date": "What's the date on {name}?",
    "total_amount": "What was the total amount paid on {name}?",
    "currency": "Which currency is {name} in?",
    "category": "Which category best fits {name}?",
    "business_purpose": "What was the business purpose of {name}?",
    "attendees": "Who attended {name}? (names / company)",
    "description": "Briefly, what was purchased on {name}?",
}


class QuestionEngine:
    def __init__(self, policy: Policy, engine: PolicyEngine) -> None:
        self._policy = policy
        self._engine = engine

    def build(self, claim: Claim) -> list[Question]:
        """Return the open questions, reusing ids of questions that are still relevant."""
        existing = {q.key: q for q in claim.questions}
        wanted: list[Question] = []
        for receipt in claim.active_receipts:
            if receipt.stage == ReceiptStage.COMPLETED:
                wanted.extend(self._for_receipt(receipt))

        # The agent infers the purpose itself; only ask if that failed once everything is read.
        still_reading = any(r.stage not in (ReceiptStage.COMPLETED, ReceiptStage.FAILED) for r in claim.active_receipts)
        if (
            self._policy.claim_requires_purpose
            and claim.active_receipts
            and not claim.purpose
            and not claim.purpose_inferring
            and not still_reading
        ):
            wanted.append(
                Question(
                    key="claim:purpose",
                    kind="purpose",
                    prompt="In a sentence, what were these expenses for? (e.g. client visit to Pune)",
                )
            )

        result: list[Question] = []
        for question in wanted:
            previous = existing.get(question.key)
            if previous:
                question.id, question.created_at = previous.id, previous.created_at
            result.append(question)
        return result

    # --------------------------------------------------------------- receipt

    def _for_receipt(self, receipt: Receipt) -> list[Question]:
        name = self._display_name(receipt)
        key = receipt.id

        if not receipt.is_receipt:
            return [
                Question(
                    key=f"{key}:not_receipt", receipt_id=key, kind="not_receipt", type="choice",
                    prompt=f"{name} doesn't look like a receipt. What should I do with it?",
                    options=[
                        {"value": "exclude", "label": "Remove it"},
                        {"value": "keep", "label": "It's a valid receipt"},
                    ],
                )
            ]

        questions: list[Question] = []
        if receipt.duplicate_of and not receipt.duplicate_acknowledged:
            questions.append(
                Question(
                    key=f"{key}:duplicate", receipt_id=key, kind="duplicate", type="choice",
                    prompt=f"{name} looks like a duplicate of one already uploaded "
                           f"{receipt.duplicate_note or 'earlier'}.",
                    options=[
                        {"value": "exclude", "label": "Remove duplicate"},
                        {"value": "keep", "label": "Keep both - they're different"},
                    ],
                )
            )
            return questions  # no point asking for details of a likely duplicate yet

        for field in receipt.missing_fields:
            questions.append(
                Question(
                    key=f"{key}:{field}", receipt_id=key, kind=field,
                    type=FIELD_TYPES.get(field, "text"),
                    prompt=FIELD_PROMPTS.get(field, "Please provide {field} for {name}.").format(name=name, field=field),
                    options=self._options_for(field),
                )
            )

        if "total_amount" in self._engine.low_confidence_fields(receipt):
            questions.append(
                Question(
                    key=f"{key}:confirm_amount", receipt_id=key, kind="confirm_amount", type="number",
                    prompt=f"I read {receipt.data.currency or ''} {receipt.data.total_amount:,.2f} on {name}, "
                           f"but the print was unclear. Is that right?",
                    default=receipt.data.total_amount,
                )
            )

        if any(f.severity == "error" and f.code == "FUTURE_DATE" for f in receipt.flags) and "date" not in receipt.missing_fields:
            questions.append(
                Question(
                    key=f"{key}:date", receipt_id=key, kind="date", type="date",
                    prompt=f"The date on {name} is in the future. What's the correct date?",
                )
            )

        if self._engine.needs_justification(receipt):
            reason = "is older than the submission window" if any(
                f.code == "STALE_RECEIPT" for f in receipt.flags
            ) else "is above the policy limit"
            questions.append(
                Question(
                    key=f"{key}:justification", receipt_id=key, kind="justification",
                    prompt=f"{name} {reason}. Add a short justification for your approver.",
                )
            )
        return questions

    def _options_for(self, field: str) -> list[dict[str, str]]:
        if field == "category":
            return [{"value": c.key, "label": f"{c.icon} {c.label}"} for c in self._policy.categories]
        if field == "currency":
            return [{"value": code, "label": code} for code in self._policy.fx_rates]
        return []

    @staticmethod
    def _display_name(receipt: Receipt) -> str:
        if receipt.data.vendor:
            return f"the **{receipt.data.vendor}** receipt"
        return f"**{receipt.file_name}**"
