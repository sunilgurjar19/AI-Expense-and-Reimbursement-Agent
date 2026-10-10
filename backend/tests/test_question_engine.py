"""QuestionEngine: the minimum set of questions needed to make a claim submittable."""

from datetime import date, timedelta

import pytest

from app.models.domain import ReceiptStage
from app.services.question_engine import QuestionEngine
from tests.helpers import make_claim, make_receipt, recent_weekday


@pytest.fixture
def questions(policy, engine) -> QuestionEngine:
    return QuestionEngine(policy, engine)


@pytest.fixture
def evaluated(engine):
    def factory(**overrides):
        receipt = make_receipt(**overrides)
        engine.evaluate(receipt)
        return receipt

    return factory


def kinds(qs) -> list[str]:
    return [q.kind for q in qs]


def test_a_complete_claim_needs_no_questions(questions, evaluated):
    assert questions.build(make_claim(evaluated(), purpose="Client visit")) == []


class TestPurposeQuestion:
    def test_asked_once_every_receipt_is_read(self, questions, evaluated):
        failed = make_receipt(stage=ReceiptStage.FAILED)
        (question,) = questions.build(make_claim(evaluated(), failed))
        assert (question.key, question.kind, question.receipt_id) == ("claim:purpose", "purpose", None)
        assert question.prompt.startswith("In a sentence, what were these expenses for?")

    @pytest.mark.parametrize(
        "situation",
        ["still-reading", "agent-inferring", "purpose-given", "only-excluded-receipts", "policy-does-not-require"],
    )
    def test_not_asked(self, questions, evaluated, policy, situation):
        claim = make_claim(evaluated())
        if situation == "still-reading":
            claim.receipts.append(make_receipt(stage=ReceiptStage.EXTRACTING))
        elif situation == "agent-inferring":
            claim.purpose_inferring = True
        elif situation == "purpose-given":
            claim.purpose = "Client visit to Pune"
        elif situation == "only-excluded-receipts":
            claim.receipts[0].excluded = True
        else:
            policy.claim_requires_purpose = False
        assert "purpose" not in kinds(questions.build(claim))


class TestReceiptQuestions:
    def test_something_that_is_not_a_receipt_gets_a_single_choice(self, questions, evaluated):
        receipt = evaluated(vendor="Zomato", is_receipt=False, total_amount=None)
        (question,) = questions.build(make_claim(receipt, purpose="x"))
        assert (question.kind, question.type, question.receipt_id) == ("not_receipt", "choice", receipt.id)
        assert question.prompt == "the **Zomato** receipt doesn't look like a receipt. What should I do with it?"
        assert [o["value"] for o in question.options] == ["exclude", "keep"]

    def test_a_likely_duplicate_is_resolved_before_asking_for_details(self, questions, evaluated):
        receipt = evaluated(vendor=None, duplicate_of="rcpt-1", duplicate_note="in this claim")
        (question,) = questions.build(make_claim(receipt, purpose="x"))
        assert question.kind == "duplicate" and question.key == f"{receipt.id}:duplicate"
        assert question.prompt == "**receipt.pdf** looks like a duplicate of one already uploaded in this claim."
        assert [o["label"] for o in question.options] == ["Remove duplicate", "Keep both - they're different"]

    def test_acknowledged_duplicates_are_not_asked_again(self, questions, evaluated):
        receipt = evaluated(duplicate_of="rcpt-1", duplicate_acknowledged=True)
        assert questions.build(make_claim(receipt, purpose="x")) == []

    def test_each_missing_field_gets_a_typed_question(self, questions, evaluated, policy):
        receipt = evaluated(vendor=None, date=None, total_amount=None, currency=None, category=None)
        qs = questions.build(make_claim(receipt, purpose="x"))

        assert [(q.kind, q.type) for q in qs] == [
            ("vendor", "text"), ("date", "date"), ("total_amount", "number"), ("currency", "select"),
            ("category", "select"),
        ]
        assert qs[0].prompt == "Who was the merchant on **receipt.pdf**?"
        assert [o["value"] for o in qs[3].options] == list(policy.fx_rates)
        assert qs[4].options[0] == {"value": "broadband", "label": "📶 Broadband Reimbursement"}
        assert len(qs[4].options) == len(policy.categories)
        assert all(q.key == f"{receipt.id}:{q.kind}" and q.receipt_id == receipt.id for q in qs)

    def test_category_specific_fields_use_their_prompts(self, questions, evaluated):
        receipt = evaluated(vendor="Smoke House Deli", category="client_entertainment", total_amount=4000.0)
        qs = questions.build(make_claim(receipt, purpose=None))
        assert kinds(qs) == ["attendees", "business_purpose", "purpose"]
        assert qs[0].prompt == "Who attended the **Smoke House Deli** receipt? (names / company)"

    def test_fields_without_a_dedicated_prompt_get_a_generic_one(self, questions, evaluated, policy):
        policy.required_fields.append("payment_method")
        (question,) = questions.build(make_claim(evaluated(vendor="Croma"), purpose="x"))
        assert (question.kind, question.type) == ("payment_method", "text")
        assert question.prompt == "Please provide payment_method for the **Croma** receipt."

    def test_an_unclear_total_is_confirmed_with_the_value_read(self, questions, evaluated):
        receipt = evaluated(vendor="IndiGo Airlines", category="airfare", total_amount=6331.5,
                            confidence={"total_amount": 0.5})
        (question,) = questions.build(make_claim(receipt, purpose="x"))
        assert (question.kind, question.type, question.default) == ("confirm_amount", "number", 6331.5)
        assert question.prompt == (
            "I read INR 6,331.50 on the **IndiGo Airlines** receipt, but the print was unclear. Is that right?"
        )

    def test_a_future_date_is_questioned(self, questions, evaluated):
        receipt = evaluated(date=(date.today() + timedelta(days=3)).isoformat())
        (question,) = questions.build(make_claim(receipt, purpose="x"))
        assert (question.kind, question.type) == ("date", "date")
        assert "is in the future" in question.prompt

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"category": "lodging", "total_amount": 17472.0}, "is above the policy limit"),
            ({"date": recent_weekday(120)}, "is older than the submission window"),
        ],
    )
    def test_policy_exceptions_need_a_justification(self, questions, evaluated, overrides, reason):
        receipt = evaluated(vendor="Taj", **overrides)
        (question,) = questions.build(make_claim(receipt, purpose="x"))
        assert question.kind == "justification"
        assert question.prompt == f"the **Taj** receipt {reason}. Add a short justification for your approver."

    def test_receipts_still_processing_or_excluded_are_not_asked_about(self, questions, evaluated):
        reading = make_receipt(vendor=None, stage=ReceiptStage.EXTRACTING)
        removed = evaluated(vendor=None, excluded=True)
        assert questions.build(make_claim(reading, removed, purpose="x")) == []


def test_question_identity_is_stable_across_rebuilds(questions, evaluated):
    claim = make_claim(evaluated(vendor=None, currency=None))
    first = questions.build(claim)
    claim.questions = first[:1]  # only the vendor question was shown so far

    second = questions.build(claim)

    assert [(q.key, q.id, q.created_at) for q in second[:1]] == [(q.key, q.id, q.created_at) for q in first[:1]]
    assert second[1].key == first[1].key and second[1].id != first[1].id  # a new question gets a new id
