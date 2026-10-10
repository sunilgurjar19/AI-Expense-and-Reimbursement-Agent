"""ClaimService: recompute (statuses, totals, groups, checklist, readiness, titles), answers and edits."""

from datetime import date, timedelta

import pytest

from app.models.api import ReceiptUpdate
from app.models.domain import ClaimStatus, Question, ReceiptStage, ReceiptStatus
from app.services.claim_service import AnswerError, ClaimService
from app.services.duplicate_detector import DuplicateDetector
from app.services.question_engine import QuestionEngine
from tests.helpers import PRIYA_ID, at, make_claim, make_receipt, recent_weekday


@pytest.fixture
def service(policy, engine, claim_repo) -> ClaimService:
    return ClaimService(
        policy=policy,
        engine=engine,
        detector=DuplicateDetector(policy.duplicate_detection),
        questions=QuestionEngine(policy, engine),
        claims=claim_repo,
    )


def recomputed(service, *receipts, **claim_fields):
    claim = make_claim(*receipts, **claim_fields)
    service.recompute(claim)
    return claim


def question(claim, kind) -> Question:
    return next(q for q in claim.questions if q.kind == kind)


def checklist(claim) -> dict[str, bool]:
    return {item.key: item.done for item in claim.checklist}


# ------------------------------------------------------------------- recompute


class TestRecomputeStatus:
    def test_submitted_claims_are_never_recomputed(self, service):
        claim = make_claim(make_receipt(vendor=None), status=ClaimStatus.SUBMITTED)
        service.recompute(claim)
        assert claim.status == ClaimStatus.SUBMITTED
        assert claim.questions == [] and claim.receipts[0].missing_fields == []

    @pytest.mark.parametrize(("purpose", "readiness"), [(None, 0), ("Client visit", 17)])
    def test_an_empty_claim_is_a_draft(self, service, purpose, readiness):
        claim = recomputed(service, purpose=purpose)
        assert (claim.status, claim.readiness, claim.title) == (ClaimStatus.DRAFT, readiness, "New expense claim")
        assert claim.questions == []

    def test_receipts_being_read_keep_the_claim_processing(self, service):
        claim = recomputed(service, make_receipt(), make_receipt(stage=ReceiptStage.EXTRACTING), purpose="Trip")
        assert claim.status == ClaimStatus.PROCESSING
        assert claim.receipts[1].status == ReceiptStatus.PROCESSING
        assert checklist(claim)["processed"] is False

    def test_a_clean_claim_with_a_purpose_is_ready(self, service):
        claim = recomputed(service, make_receipt(), make_receipt(vendor="Ola Cabs"), purpose="Client visit")
        assert claim.status == ClaimStatus.READY and claim.readiness == 100
        assert all(checklist(claim).values())
        assert [r.status for r in claim.receipts] == [ReceiptStatus.COMPLETE] * 2

    def test_open_questions_mean_needs_attention(self, service):
        claim = recomputed(service, make_receipt(), purpose=None)
        assert claim.status == ClaimStatus.NEEDS_ATTENTION
        assert [q.kind for q in claim.questions] == ["purpose"]
        assert checklist(claim) == {"uploaded": True, "processed": True, "details": True, "policy": True,
                                    "duplicates": True, "purpose": False}
        assert claim.readiness == 83

    def test_a_failed_receipt_blocks_submission(self, service):
        claim = recomputed(service, make_receipt(), make_receipt(stage=ReceiptStage.FAILED), purpose="Trip")
        assert claim.status == ClaimStatus.NEEDS_ATTENTION
        assert checklist(claim)["processed"] is False

    def test_receipt_status_reflects_what_is_still_needed(self, service):
        receipts = {
            "excluded": make_receipt(excluded=True),
            "failed": make_receipt(stage=ReceiptStage.FAILED),
            "processing": make_receipt(stage=ReceiptStage.READING),
            "needs_info": make_receipt(vendor=None),
            "question": make_receipt(category="lodging", total_amount=17472.0),  # justification question
            "error_flag": make_receipt(currency="XYZ"),  # unsupported currency: an error but no question
            "complete": make_receipt(),
        }
        claim = recomputed(service, *receipts.values(), purpose="Trip")
        assert {name: r.status.value for name, r in receipts.items()} == {
            "excluded": "excluded",
            "failed": "failed",
            "processing": "processing",
            "needs_info": "needs_info",
            "question": "questionable",
            "error_flag": "questionable",
            "complete": "complete",
        }
        assert checklist(claim)["details"] is False and checklist(claim)["policy"] is False


class TestTotalsAndGroups:
    def test_totals_groups_and_period_use_completed_active_receipts(self, service):
        claim = recomputed(
            service,
            make_receipt(vendor="Taj", category="lodging", total_amount=17472.0, date="2026-10-03"),
            make_receipt(vendor="IndiGo", category="airfare", total_amount=6331.5, date="2026-10-01"),
            make_receipt(vendor="Uber", category="local_conveyance", total_amount=827.3, date="2026-10-02"),
            make_receipt(vendor="Uber", category="local_conveyance", total_amount=827.3, excluded=True),
            make_receipt(vendor="Ola", category="local_conveyance", total_amount=999.0, stage=ReceiptStage.READING,
                         date="2026-09-01"),
            purpose="Trip",
        )
        assert claim.total_claimed == 24630.8
        assert claim.total_reimbursable == 16158.8  # the hotel is capped at 9,000
        assert [(g.category, g.label, g.icon, g.count, g.total) for g in claim.groups] == [
            ("lodging", "Hotel & Lodging", "🏨", 1, 17472.0),
            ("airfare", "Airfare", "✈️", 1, 6331.5),
            ("local_conveyance", "Local Conveyance & Toll Tax", "🚕", 1, 827.3),
        ]
        assert (claim.period_start, claim.period_end) == ("2026-10-01", "2026-10-03")

    def test_uncategorised_and_unknown_categories_get_fallback_groups(self, service):
        claim = recomputed(service, make_receipt(category=None, total_amount=300.0),
                           make_receipt(category="misc_stuff", total_amount=200.0), purpose="x")
        assert [(g.category, g.label, g.icon) for g in claim.groups] == [
            ("other", "Other Reimbursement", "🧾"),
            ("misc_stuff", "Misc_Stuff", "🧾"),
        ]


class TestAutoTitle:
    @pytest.mark.parametrize(
        ("dates", "expected"),
        [
            (["2026-10-05"], "Expenses · 05 Oct 2026"),
            (["2026-10-01", "2026-10-03"], "Expenses · 1–03 Oct 2026"),
            (["2026-09-28", "2026-10-03"], "Expenses · 28 Sep – 03 Oct 2026"),
        ],
        ids=["single-day", "same-month", "across-months"],
    )
    def test_period_formats(self, service, dates, expected):
        claim = recomputed(service, *(make_receipt(date=d, location="Pune") for d in dates), purpose="x")
        assert claim.title == expected

    def test_trips_are_named_after_the_most_visited_city(self, service):
        claim = recomputed(
            service,
            make_receipt(vendor="IndiGo", category="airfare", date="2026-10-01", location="Mumbai"),
            make_receipt(vendor="Taj", category="lodging", date="2026-10-02", location="bengaluru"),
            make_receipt(vendor="Uber", category="local_conveyance", date="2026-10-03", location="bengaluru"),
            purpose="x",
        )
        assert claim.title == "Bengaluru trip · 1–03 Oct 2026"

    def test_travel_without_a_known_city_is_plain_expenses(self, service):
        claim = recomputed(service, make_receipt(category="airfare", date="2026-10-05", location=None), purpose="x")
        assert claim.title == "Expenses · 05 Oct 2026"

    def test_a_title_typed_by_the_employee_is_kept(self, service):
        claim = recomputed(service, make_receipt(date="2026-10-05"), title="Q3 offsite", title_is_auto=False)
        assert claim.title == "Q3 offsite"


class TestDuplicates:
    def test_second_copy_in_the_same_claim(self, service):
        original = make_receipt(sha256="abc", uploaded_at=at(0))
        copy = make_receipt(sha256="abc", uploaded_at=at(1))
        claim = recomputed(service, original, copy, purpose="x")
        assert (copy.duplicate_of, copy.duplicate_note) == (original.id, "in this claim")
        assert original.duplicate_of is None and "POSSIBLE_DUPLICATE" in [f.code for f in copy.flags]
        assert checklist(claim)["duplicates"] is False and question(claim, "duplicate").receipt_id == copy.id

    @pytest.mark.parametrize(("reference", "note"), [("EXP-2026-00001", "in your claim “Delhi trip” (EXP-2026-00001)"),
                                                     (None, "in your claim “Delhi trip”")])
    def test_copy_of_a_receipt_from_another_claim(self, service, claim_repo, reference, note):
        earlier = make_claim(make_receipt(sha256="abc", uploaded_at=at(0)), title="Delhi trip", reference_no=reference,
                             status=ClaimStatus.SUBMITTED)
        claim_repo.save(earlier)
        copy = make_receipt(sha256="abc", uploaded_at=at(10))
        recomputed(service, copy, purpose="x")
        assert copy.duplicate_of == earlier.receipts[0].id and copy.duplicate_note == note

    def test_other_employees_receipts_are_not_compared(self, service, claim_repo):
        claim_repo.save(make_claim(make_receipt(sha256="abc", uploaded_at=at(0)), user_id=PRIYA_ID))
        copy = make_receipt(sha256="abc", uploaded_at=at(10))
        recomputed(service, copy, purpose="x")
        assert copy.duplicate_of is None and copy.duplicate_note is None

    def test_acknowledgement_resets_only_when_the_matched_original_changes(self, service):
        original = make_receipt(sha256="abc", uploaded_at=at(0))
        copy = make_receipt(sha256="abc", uploaded_at=at(1), duplicate_of=original.id, duplicate_acknowledged=True)
        service.check_receipt(copy, [original, copy])
        assert copy.duplicate_acknowledged is True

        copy.duplicate_of = "rcpt-some-other"
        service.check_receipt(copy, [original, copy])
        assert (copy.duplicate_of, copy.duplicate_acknowledged) == (original.id, False)


class TestPurposeInheritance:
    def test_receipts_needing_a_business_purpose_reuse_the_claim_remarks(self, service):
        meal = make_receipt(vendor="Starbucks", category="meals", total_amount=490.0)
        claim = recomputed(service, meal, purpose="Client visit to Pune")
        assert (meal.data.business_purpose, meal.purpose_inherited) == ("Client visit to Pune", True)
        assert meal.missing_fields == [] and claim.status == ClaimStatus.READY

    def test_a_purpose_written_for_the_receipt_is_kept(self, service):
        meal = make_receipt(category="meals", total_amount=490.0, business_purpose="Team lunch")
        recomputed(service, meal, purpose="Client visit")
        assert (meal.data.business_purpose, meal.purpose_inherited) == ("Team lunch", False)

    def test_inherited_purpose_follows_the_claim_remarks(self, service):
        meal = make_receipt(category="meals", total_amount=490.0)
        claim = recomputed(service, meal, purpose="Client visit")
        claim.purpose = "Sales offsite"
        service.recompute(claim)
        assert meal.data.business_purpose == "Sales offsite"

        claim.purpose = None
        service.recompute(claim)
        assert (meal.data.business_purpose, meal.purpose_inherited) == (None, False)
        assert meal.missing_fields == ["business_purpose"] and meal.status == ReceiptStatus.NEEDS_INFO

    def test_inherited_purpose_is_dropped_when_the_category_no_longer_needs_it(self, service):
        receipt = make_receipt(category="meals", total_amount=490.0)
        claim = recomputed(service, receipt, purpose="Client visit")
        receipt.data.category = "airfare"
        service.recompute(claim)
        assert (receipt.data.business_purpose, receipt.purpose_inherited) == (None, False)

    def test_categories_without_the_requirement_never_inherit(self, service):
        receipt = make_receipt(category="airfare")
        recomputed(service, receipt, purpose="Client visit")
        assert receipt.data.business_purpose is None


# --------------------------------------------------------------------- answers


class TestApplyAnswer:
    def test_purpose_answer_becomes_the_employees_remarks(self, service):
        claim = recomputed(service, make_receipt())
        echo = service.apply_answer(claim, question(claim, "purpose"), "  Client visit to Pune  ")
        assert echo == claim.purpose == "Client visit to Pune" and claim.purpose_source == "user"

    @pytest.mark.parametrize(
        ("answer", "excluded", "acknowledged", "echo"),
        [("exclude", True, False, "Remove duplicate"), ("keep", False, True, "Keep both - they're different")],
    )
    def test_duplicate_choice(self, service, answer, excluded, acknowledged, echo):
        copy = make_receipt(sha256="abc", uploaded_at=at(1))
        claim = recomputed(service, make_receipt(sha256="abc", uploaded_at=at(0)), copy, purpose="x")
        assert service.apply_answer(claim, question(claim, "duplicate"), answer) == echo
        assert (copy.excluded, copy.duplicate_acknowledged) == (excluded, acknowledged)

    @pytest.mark.parametrize(("answer", "excluded", "is_receipt"), [("exclude", True, False), ("keep", False, True)])
    def test_not_a_receipt_choice(self, service, answer, excluded, is_receipt):
        receipt = make_receipt(is_receipt=False)
        claim = recomputed(service, receipt, purpose="x")
        service.apply_answer(claim, question(claim, "not_receipt"), answer)
        assert (receipt.excluded, receipt.is_receipt) == (excluded, is_receipt)

    def test_choice_questions_only_accept_their_options(self, service):
        claim = recomputed(service, make_receipt(is_receipt=False), purpose="x")
        with pytest.raises(AnswerError, match="Choose one of the options"):
            service.apply_answer(claim, question(claim, "not_receipt"), "maybe")

    def test_justification_is_stored_and_must_not_be_blank(self, service):
        receipt = make_receipt(category="lodging", total_amount=17472.0)
        claim = recomputed(service, receipt, purpose="x")
        with pytest.raises(AnswerError, match="Please type an answer"):
            service.apply_answer(claim, question(claim, "justification"), "   ")
        assert service.apply_answer(claim, question(claim, "justification"), "Conference hotel") == "Conference hotel"
        service.recompute(claim)
        assert receipt.justification == "Conference hotel" and claim.status == ClaimStatus.READY

    def test_confirming_an_amount_records_it_as_confirmed(self, service):
        receipt = make_receipt(total_amount=6331.5, confidence={"total_amount": 0.5})
        claim = recomputed(service, receipt, purpose="x")
        assert service.apply_answer(claim, question(claim, "confirm_amount"), "Rs. 6,400") == "6,400.00"
        assert receipt.data.total_amount == 6400.0 and receipt.confidence["total_amount"] == 1.0
        assert "total_amount" in receipt.confirmed_fields

    def test_field_answer_is_echoed_as_text(self, service):
        receipt = make_receipt(date=None)
        claim = recomputed(service, receipt, purpose="x")
        bill_date = recent_weekday(4)
        assert service.apply_answer(claim, question(claim, "date"), bill_date) == bill_date

    def test_question_for_a_deleted_receipt(self, service):
        claim = recomputed(service, make_receipt(vendor=None), purpose="x")
        stale_question = question(claim, "vendor")
        claim.receipts.clear()
        with pytest.raises(AnswerError, match="no longer exists"):
            service.apply_answer(claim, stale_question, "Uber")


class TestSetPurpose:
    def test_employee_remarks_win_over_the_agent(self, service):
        claim = make_claim()
        service.set_purpose(claim, "Agent guess", source="agent")
        assert (claim.purpose, claim.purpose_source) == ("Agent guess", "agent")
        service.set_purpose(claim, "Client visit")
        assert (claim.purpose, claim.purpose_source) == ("Client visit", "user")
        service.set_purpose(claim, "Another agent guess", source="agent")
        assert (claim.purpose, claim.purpose_source) == ("Client visit", "user")

    def test_agent_may_refresh_its_own_remarks(self, service):
        claim = make_claim()
        service.set_purpose(claim, "First guess", source="agent")
        service.set_purpose(claim, "Better guess", source="agent")
        assert claim.purpose == "Better guess"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_remarks_clear_the_purpose(self, service, blank):
        claim = make_claim(purpose="Old")
        service.set_purpose(claim, blank)
        assert (claim.purpose, claim.purpose_source) == (None, None)

    def test_remarks_are_capped_at_500_characters(self, service):
        claim = make_claim()
        service.set_purpose(claim, "x" * 800)
        assert len(claim.purpose) == 500


class TestApplyUpdate:
    def test_expense_fields_are_validated_confirmed_and_clear_the_read_warning(self, service):
        receipt = make_receipt(read_warning="Couldn't read the photo", vendor=None)
        service.apply_update(receipt, ReceiptUpdate(vendor=" Chai Point ", total_amount=270, currency="rs"))
        assert (receipt.data.vendor, receipt.data.total_amount, receipt.data.currency) == ("Chai Point", 270.0, "INR")
        assert receipt.read_warning is None
        assert receipt.confirmed_fields == ["vendor", "total_amount", "currency"]

    def test_only_fields_that_were_sent_are_touched(self, service):
        receipt = make_receipt(vendor="Uber India", location="Pune")
        service.apply_update(receipt, ReceiptUpdate.model_validate({"vendor": "Uber"}))
        assert (receipt.data.vendor, receipt.data.location) == ("Uber", "Pune")

    def test_exclusion_and_justification(self, service):
        receipt = make_receipt(justification="Old reason", read_warning="unreadable")
        service.apply_update(receipt, ReceiptUpdate(excluded=True, justification=""))
        assert (receipt.excluded, receipt.justification) == (True, None)
        assert receipt.read_warning == "unreadable"  # no expense details were provided

    def test_manual_details_rescue_a_failed_receipt(self, service):
        receipt = make_receipt(stage=ReceiptStage.FAILED, progress=100, error="Ollama request failed")
        service.apply_update(receipt, ReceiptUpdate(total_amount=500))
        assert (receipt.stage, receipt.progress, receipt.error, receipt.extraction_source) == (
            ReceiptStage.COMPLETED, 100, None, "manual")

    def test_a_justification_alone_does_not_rescue_a_failed_receipt(self, service):
        receipt = make_receipt(stage=ReceiptStage.FAILED, error="boom")
        service.apply_update(receipt, ReceiptUpdate(justification="Please accept"))
        assert receipt.stage == ReceiptStage.FAILED

    def test_invalid_values_are_rejected(self, service):
        with pytest.raises(AnswerError, match="valid amount"):
            service.apply_update(make_receipt(), ReceiptUpdate(total_amount=-5))


class TestSetField:
    @pytest.mark.parametrize(
        ("field", "value", "stored"),
        [
            ("total_amount", "Rs. 1,250", 1250.0),
            ("tax_amount", 18, 18.0),
            ("total_amount", 0, 0.0),
            ("date", "05/10/2026", "2026-10-05"),
            ("currency", "usd", "USD"),
            ("currency", "₹", "INR"),
            ("category", "meals", "meals"),
            ("vendor", "  Blue Tokai  ", "Blue Tokai"),
            ("description", "x" * 600, "x" * 500),
            ("attendees", 3, "3"),
        ],
    )
    def test_valid_values_are_normalised_and_confirmed(self, service, field, value, stored):
        receipt = make_receipt()
        service.set_field(receipt, field, value)
        assert getattr(receipt.data, field) == stored
        assert receipt.confidence[field] == 1.0 and receipt.confirmed_fields == [field]

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("payment", "Card", "Unknown field payment"),
            ("justification", "x", "Unknown field justification"),
            ("total_amount", "-5", "Please enter a valid amount"),
            ("total_amount", "abc", "Please enter a valid amount"),
            ("date", "31/02/2026", r"Please enter a valid date \(YYYY-MM-DD\)"),
            ("currency", "XYZ", "Unsupported currency"),
            ("currency", "", "Unsupported currency"),
            ("category", "groceries", "Unknown category"),
            ("vendor", "   ", "Please type an answer"),
            ("vendor", None, "Please type an answer"),
        ],
    )
    def test_invalid_values_raise_answer_error(self, service, field, value, message):
        receipt = make_receipt()
        with pytest.raises(AnswerError, match=message):
            service.set_field(receipt, field, value)
        assert receipt.confirmed_fields == []

    def test_confirming_twice_lists_the_field_once(self, service):
        receipt = make_receipt()
        service.set_field(receipt, "vendor", "A")
        service.set_field(receipt, "vendor", "B")
        assert receipt.confirmed_fields == ["vendor"]

    def test_a_typed_business_purpose_is_no_longer_inherited(self, service):
        receipt = make_receipt(business_purpose="Claim remarks", purpose_inherited=True)
        service.set_field(receipt, "business_purpose", "Dinner with the Acme team")
        assert receipt.purpose_inherited is False


def test_future_receipt_dates_produce_a_date_question(service):
    claim = recomputed(service, make_receipt(date=(date.today() + timedelta(days=2)).isoformat()), purpose="x")
    assert [q.kind for q in claim.questions] == ["date"] and claim.receipts[0].status == ReceiptStatus.QUESTIONABLE
