"""ChatGuard: model-proposed chat actions are applied only when the employee actually said them."""

import pytest

from app.models.domain import Question
from app.services.chat_guard import ChatGuard, is_question

# Seen live with gemma3:4b: asked "What's my total?", it "answered" the pending justification by
# paraphrasing the question itself.
JUSTIFICATION_PROMPT = ("the **Taj MG Road Bengaluru** receipt is above the policy limit. "
                        "Add a short justification for your approver.")
ECHOED_ANSWER = "Please add a short justification for the Taj MG Road Bengaluru receipt exceeding the policy limit."


@pytest.fixture
def guard(policy) -> ChatGuard:
    return ChatGuard(policy)


def ask(kind: str, type_: str = "text", prompt: str = "Tell me more", **extra) -> Question:
    return Question(key=f"rcpt-1:{kind}", receipt_id="rcpt-1", kind=kind, type=type_, prompt=prompt, **extra)


@pytest.mark.parametrize(("message", "expected"), [("What's my total?", True), ("Is it ready?  ", True),
                                                    ("It was a client dinner.", False), ("", False)])
def test_is_question(message, expected):
    assert is_question(message) is expected


class TestTextAnswers:
    def test_an_answer_the_employee_wrote_is_accepted(self, guard):
        question = ask("justification", prompt=JUSTIFICATION_PROMPT)
        message = "The Taj was the client's venue for the workshop and the company hotel was sold out."
        assert guard.answer(question, "Client's venue for the workshop; company hotel sold out", message)

    def test_the_observed_misfire_is_rejected(self, guard):
        question = ask("justification", prompt=JUSTIFICATION_PROMPT)
        assert not guard.answer(question, ECHOED_ANSWER, "What's my total?")

    def test_a_question_is_never_an_answer(self, guard):
        question = ask("justification")
        assert not guard.answer(question, "client venue", "Is 'client venue' a good enough justification?")

    def test_echoing_the_question_is_not_an_answer(self, guard):
        question = ask("justification", prompt=JUSTIFICATION_PROMPT)
        message = f"{ECHOED_ANSWER} Hmm."  # even when the words are in the message
        assert not guard.answer(question, ECHOED_ANSWER, message)

    def test_restating_the_task_in_a_statement_is_not_an_answer(self, guard):
        question = ask("justification", prompt=JUSTIFICATION_PROMPT)
        message = "I'll add a short justification for the Taj receipt later."
        assert not guard.answer(question, "add a short justification for the Taj receipt later", message)

    def test_an_answer_matching_the_questions_example_is_fine(self, guard):
        question = ask("purpose", prompt="In a sentence, what were these expenses for? (e.g. client visit to Pune)")
        assert guard.answer(question, "Client visit to Pune", "Client visit to Pune")

    def test_an_answer_may_reuse_some_of_the_questions_words(self, guard):
        question = ask("business_purpose", prompt="What was the business purpose of the **Starbucks Coffee** receipt?")
        message = "Business purpose: meeting with the client at Starbucks"
        assert guard.answer(question, message, message)

    @pytest.mark.parametrize("value", [None, "", "   ", "null"])
    def test_empty_values_are_rejected(self, guard, value):
        assert not guard.answer(ask("attendees"), value, "Rohan and Anita from Infosys")

    def test_short_answers_are_judged_on_the_message_alone(self, guard):
        assert guard.answer(ask("attendees"), "Rohan", "Just Rohan")
        assert not guard.answer(ask("description"), "it is", "something else entirely")

    def test_small_wording_differences_are_tolerated(self, guard):
        assert guard.answer(ask("attendees"), "Rohan, Anita (Infosys)", "attendees were rohan and anita from infosys")


class TestNumberAndDateAnswers:
    @pytest.mark.parametrize("message", ["It was 1,500", "The total was ₹1500.00", "1500"])
    def test_amounts_must_be_in_the_message(self, guard, message):
        assert guard.answer(ask("total_amount", "number"), 1500, message)
        assert not guard.answer(ask("total_amount", "number"), 150, message)

    def test_a_confirmation_accepts_the_amount_that_was_read(self, guard):
        question = ask("confirm_amount", "number", default=827.3)
        assert guard.answer(question, 827.3, "yes, that's right")
        assert not guard.answer(question, 900, "yes")
        assert guard.answer(question, 850, "No, it was 850")

    @pytest.mark.parametrize("message", ["It was on 5 Oct 2026", "date: 05/10/2026", "the 5th of October",
                                         "05-10-26", "on 5/10"])
    def test_dates_must_be_in_the_message(self, guard, message):
        assert guard.answer(ask("date", "date"), "2026-10-05", message)

    @pytest.mark.parametrize("message", ["yesterday", "the 6th of October", "5 Nov", "my doctor visit on the 5th"])
    def test_unstated_dates_are_rejected(self, guard, message):
        assert not guard.answer(ask("date", "date"), "2026-10-05", message)

    def test_unparseable_dates_are_rejected(self, guard):
        assert not guard.answer(ask("date", "date"), "soon", "soon")


class TestChoices:
    duplicate = ask("duplicate", "choice", options=[{"value": "exclude", "label": "Remove duplicate"},
                                                    {"value": "keep", "label": "Keep both - they're different"}])

    @pytest.mark.parametrize(("message", "value"), [
        ("Please remove the duplicate", "exclude"),
        ("Can you delete the second Uber one?", "exclude"),  # a request phrased as a question is fine
        ("Keep both, they're different trips", "keep"),
    ])
    def test_an_explicit_request_picks_the_option(self, guard, message, value):
        assert guard.answer(self.duplicate, value, message)

    @pytest.mark.parametrize("message", ["Is the Uber receipt a duplicate?", "What's my total?", "ok"])
    def test_without_a_request_nothing_is_picked(self, guard, message):
        assert not guard.answer(self.duplicate, "exclude", message)

    def test_unknown_options_are_rejected(self, guard):
        assert not guard.answer(self.duplicate, "archive", "remove it")


class TestCategoryAndCurrency:
    @pytest.mark.parametrize(("value", "message"), [
        ("lodging", "It was a hotel stay"),
        ("local_conveyance", "That one was a cab to the airport"),  # a policy keyword
        ("meals", "team lunch"),
        ("fuel_two_wheeler", "petrol for my bike"),
    ])
    def test_a_category_the_employee_named_is_accepted(self, guard, value, message):
        assert guard.answer(ask("category", "select"), value, message)
        assert guard.update("category", value, message)

    @pytest.mark.parametrize(("value", "message"), [
        ("medical", "please process my reimbursement"),  # generic label words don't count
        ("lodging", "What's my total?"),
        ("made_up", "made up"),
    ])
    def test_unstated_or_unknown_categories_are_rejected(self, guard, value, message):
        assert not guard.update("category", value, message)

    @pytest.mark.parametrize(("value", "message"), [
        ("USD", "I paid in dollars"), ("USD", "it was USD 40"), ("INR", "₹ 250"), ("SGD", "S$ 20 at the hawker centre"),
        ("EUR", "in euros"),
    ])
    def test_a_currency_the_employee_named_is_accepted(self, guard, value, message):
        assert guard.answer(ask("currency", "select"), value, message)

    @pytest.mark.parametrize(("value", "message"), [("USD", "it was 40"), ("EUR", "it was in dollars"), (None, "dollars")])
    def test_unstated_currencies_are_rejected(self, guard, value, message):
        assert not guard.update("currency", value, message)


class TestUpdates:
    def test_a_correction_the_employee_asked_for_is_accepted(self, guard):
        assert guard.update("vendor", "Blue Tokai", "The merchant was Blue Tokai")
        assert guard.update("vendor", "Blue Tokai", "Can you change the merchant to Blue Tokai?")

    def test_a_correction_nobody_asked_for_is_rejected(self, guard):
        assert not guard.update("vendor", "Starbucks", "hello")

    def test_amounts_and_dates(self, guard):
        assert guard.update("total_amount", "1848", "The total was Rs. 1,848")
        assert not guard.update("tax_amount", 88, "The total was Rs. 1,848")
        assert guard.update("date", "2026-10-01", "date should be 01/10/2026")
        assert not guard.update("date", "2026-10-01", "fix the date please")


class TestRemarks:
    AGENT_REMARKS = "Business trip to Bengaluru, 29 Sep - 2 Oct 2026 - airfare, hotel & lodging and meals."

    def test_remarks_can_be_set_when_there_are_none(self, guard):
        assert guard.purpose("Client workshop in Pune", "We went to Pune for a client workshop", None)

    def test_a_passing_remark_does_not_replace_existing_remarks(self, guard):
        message = "The Taj was the client's venue for the workshop and the company hotel was sold out."
        assert not guard.purpose(message, message, self.AGENT_REMARKS)

    @pytest.mark.parametrize("message", ["The purpose was a client workshop in Pune",
                                         "Change the remarks to: client workshop in Pune",
                                         "The trip was for a client workshop in Pune"])
    def test_existing_remarks_are_replaced_when_asked(self, guard, message):
        assert guard.purpose("client workshop in Pune", message, self.AGENT_REMARKS)

    def test_remarks_must_come_from_the_message(self, guard):
        assert not guard.purpose("Sales offsite", "We went to Pune", None)

    def test_a_question_does_not_set_remarks(self, guard):
        assert not guard.purpose("client workshop", "Was it a client workshop?", None)


class TestOwnWordsAnswer:
    """The employee's own statement may answer a narrative question the model targeted but garbled."""

    STATEMENT = "The Taj was the client's venue for the workshop and the company hotel was sold out."

    def test_a_substantive_statement_answers_a_justification(self, guard):
        assert guard.own_words_answer(ask("justification", prompt=JUSTIFICATION_PROMPT), self.STATEMENT)

    @pytest.mark.parametrize("message", [
        "What's my total?",                                       # a question
        "ok thanks",                                              # not substantive
        "Add a short justification for the Taj receipt above the policy limit.",  # restates the question
    ])
    def test_other_messages_do_not(self, guard, message):
        assert not guard.own_words_answer(ask("justification", prompt=JUSTIFICATION_PROMPT), message)

    def test_only_for_narrative_questions(self, guard):
        assert not guard.own_words_answer(ask("vendor"), "The merchant was the Blue Tokai cafe in Indiranagar")
