"""DuplicateDetector: exact file hashes and fuzzy vendor/amount/date/invoice matching."""

import pytest

from app.models.domain import ReceiptStage
from app.models.policy import DuplicateRule
from app.services.duplicate_detector import DuplicateDetector
from tests.helpers import at, make_receipt


@pytest.fixture
def detector(policy) -> DuplicateDetector:
    return DuplicateDetector(policy.duplicate_detection)  # tolerance 1.0, window 2 days, similarity 0.75


def uber(minute: int, **overrides):
    values = {"vendor": "Uber India", "total_amount": 827.3, "amount_in_base": 827.3, "date": "2026-09-30",
              "uploaded_at": at(minute)}
    values.update(overrides)
    return make_receipt(**values)


def test_identical_file_flags_only_the_later_copy(detector):
    original = uber(0, sha256="same-bytes")
    copy = uber(5, sha256="same-bytes")
    assert detector.find(copy, [original, copy]) == original.id
    assert detector.find(original, [original, copy]) is None


def test_identical_file_is_caught_even_while_the_original_is_still_being_read(detector):
    original = uber(0, sha256="same-bytes", stage=ReceiptStage.EXTRACTING, amount_in_base=None)
    copy = uber(5, sha256="same-bytes")
    assert detector.find(copy, [original]) == original.id


def test_same_expense_photographed_twice_is_caught_by_fuzzy_matching(detector):
    original = uber(0)
    photo = uber(5, vendor="UBER INDIA", amount_in_base=827.8, date="2026-10-01")
    assert detector.find(photo, [original]) == original.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_in_base": 829.0},  # more than the 1.0 tolerance apart
        {"date": "2026-10-03"},  # outside the 2-day window
        {"vendor": "Ola Cabs"},  # different merchant
        {"amount_in_base": None},  # unknown amount: can't compare
        {"date": None},
    ],
    ids=["amount", "date", "vendor", "no-amount", "no-date"],
)
def test_different_expenses_are_not_duplicates(detector, overrides):
    assert detector.find(uber(5, **overrides), [uber(0)]) is None


def test_matching_invoice_number_beats_vendor_spelling(detector):
    original = uber(0, vendor="Uber India", invoice_number="INV-42")
    later = uber(5, vendor="Rasier Operations BV", invoice_number="INV-42")
    assert detector.find(later, [original]) == original.id


def test_fuzzy_matching_only_compares_against_completed_receipts(detector):
    still_reading = uber(0, stage=ReceiptStage.VALIDATING)
    assert detector.find(uber(5), [still_reading]) is None


def test_excluded_receipts_are_never_originals(detector):
    removed = uber(0, sha256="same-bytes", excluded=True)
    assert detector.find(uber(5, sha256="same-bytes"), [removed]) is None


def test_a_receipt_never_duplicates_itself(detector):
    receipt = uber(0)
    assert detector.find(receipt, [receipt]) is None


def test_upload_time_ties_are_broken_by_id(detector):
    first = uber(0, id="rcpt-a", sha256="same-bytes")
    second = uber(0, id="rcpt-b", sha256="same-bytes")
    assert detector.find(second, [first, second]) == "rcpt-a"
    assert detector.find(first, [first, second]) is None


def test_thresholds_come_from_the_policy_rule():
    strict = DuplicateDetector(DuplicateRule(amount_tolerance=0, date_window_days=0, vendor_similarity=1.0))
    original = uber(0)
    assert strict.find(uber(5), [original]) == original.id
    assert strict.find(uber(5, amount_in_base=827.4), [original]) is None
    assert strict.find(uber(5, date="2026-10-01"), [original]) is None
    assert strict.find(uber(5, vendor="Uber India Pvt"), [original]) is None
