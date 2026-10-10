"""PolicyEngine: categorisation and the per-receipt policy checks, against the real config/policy.yaml."""

from datetime import date, timedelta

import pytest

from app.models.domain import Flag, LineItem
from app.services.policy_engine import PolicyEngine, _keyword_in
from tests.helpers import make_receipt, recent_weekday, recent_weekend_day


def codes(receipt) -> list[str]:
    return [f.code for f in receipt.flags]


def flag(receipt, code):
    return next(f for f in receipt.flags if f.code == code)


# ------------------------------------------------------------------ categorise


class TestCategorise:
    def test_a_specific_model_category_is_kept(self, engine):
        receipt = make_receipt(vendor="Unrelated Name", category="airfare")
        assert engine.categorise(receipt) == "airfare"

    @pytest.mark.parametrize(
        ("category", "vendor", "expected"),
        [
            (None, "Uber India", "local_conveyance"),
            ("other", "Starbucks Coffee", "meals"),
            ("not_a_policy_key", "Taj MG Road Bengaluru", "lodging"),
            (None, "Apollo Pharmacy", "medical"),
            (None, "JioFiber", "broadband"),
            (None, "Acme Widgets Pvt Ltd", "other"),  # no keyword at all
        ],
    )
    def test_missing_or_generic_category_is_inferred_from_keywords(self, engine, category, vendor, expected):
        assert engine.categorise(make_receipt(vendor=vendor, category=category)) == expected

    def test_a_model_category_ruled_out_by_an_exclude_word_is_re_inferred(self, engine):
        receipt = make_receipt(vendor="Manish Service Center", category="fuel_two_wheeler",
                               line_items=[{"description": "Diesel 10 L", "amount": 900}])
        assert engine.categorise(receipt) == "fuel_car"

    def test_keyword_ties_go_to_the_category_listed_first(self, engine):
        receipt = make_receipt(vendor="Indian Oil", category=None, line_items=[{"description": "Petrol", "amount": 300}])
        assert engine.categorise(receipt) == "fuel_car"  # fuel_car precedes fuel_two_wheeler in policy.yaml

    def test_more_keyword_hits_win(self, engine):
        receipt = make_receipt(vendor="Indian Oil - Shree Sai Fuels", category=None)
        text = "Vehicle: Two Wheeler (Activa)  MH-02-AB-1234\nPetrol 3.20 L x 104.21     333.47"
        assert engine.categorise(receipt, raw_text=text) == "fuel_two_wheeler"

    @pytest.mark.parametrize(
        ("vendor", "expected"),
        [("शर्मा पेट्रोल पंप", "fuel_car"), ("राम मेडिकल स्टोर", "medical"), ("सरस्वती विद्यालय", "children_education")],
    )
    def test_indic_keywords_match_as_substrings(self, engine, vendor, expected):
        assert engine.categorise(make_receipt(vendor=vendor, category=None)) == expected

    def test_file_name_and_text_layer_are_part_of_the_evidence(self, engine):
        by_name = make_receipt(vendor=None, category=None, file_name="uber_trip-receipt.pdf")
        by_text = make_receipt(vendor=None, category=None, file_name="scan.pdf")
        assert engine.categorise(by_name) == "local_conveyance"
        assert engine.categorise(by_text, raw_text="IRCTC e-ticket, train 12951") == "rail_bus"


@pytest.mark.parametrize(
    ("keyword", "haystack", "expected"),
    [
        ("uber", "uber india", True),
        ("auto", "autodesk store", False),  # Latin keywords match whole words only
        ("toll tax", "nhai toll tax receipt", True),
        ("  Cab ", "a cab ride", True),
        ("पेट्रोल", "पेट्रोलपंप", True),  # Indic keywords match as substrings
        ("पेट्रोल", "डीजल", False),
    ],
)
def test_keyword_in(keyword, haystack, expected):
    assert _keyword_in(keyword, haystack) is expected


# -------------------------------------------------------------------- evaluate


class TestRequiredFields:
    def test_a_clean_receipt_passes_without_flags(self, engine):
        receipt = make_receipt()
        engine.evaluate(receipt)
        assert (receipt.flags, receipt.missing_fields) == ([], [])
        assert receipt.amount_in_base == receipt.reimbursable_amount == 450.0

    def test_missing_global_required_fields_are_listed(self, engine):
        receipt = make_receipt(vendor=None, currency=None, category=None)
        engine.evaluate(receipt)
        assert receipt.missing_fields == ["vendor", "currency", "category"]
        assert receipt.amount_in_base == 450.0  # no currency: the base currency is assumed for conversion

    @pytest.mark.parametrize(
        ("category", "missing"),
        [
            ("meals", ["business_purpose"]),
            ("client_entertainment", ["attendees", "business_purpose"]),
            ("other", ["description"]),
            ("airfare", []),
        ],
    )
    def test_category_specific_requirements(self, engine, category, missing):
        receipt = make_receipt(category=category, total_amount=200.0)
        engine.evaluate(receipt)
        assert receipt.missing_fields == missing

    def test_provided_category_requirements_are_not_missing(self, engine):
        receipt = make_receipt(category="client_entertainment", attendees="Acme CFO", business_purpose="Deal review")
        engine.evaluate(receipt)
        assert receipt.missing_fields == []

    def test_an_unparseable_date_counts_as_missing(self, engine):
        receipt = make_receipt(date="2026-02-30")
        engine.evaluate(receipt)
        assert receipt.missing_fields == ["date"]
        assert codes(receipt) == []


class TestDocumentFlags:
    def test_unreadable_document_warning(self, engine):
        receipt = make_receipt(read_warning="Couldn't read this photo.")
        engine.evaluate(receipt)
        assert (flag(receipt, "UNREADABLE").severity, flag(receipt, "UNREADABLE").message) == (
            "warning", "Couldn't read this photo.")

    def test_not_a_receipt_is_an_error(self, engine):
        receipt = make_receipt(is_receipt=False)
        engine.evaluate(receipt)
        assert flag(receipt, "NOT_A_RECEIPT").severity == "error"


class TestDates:
    def test_future_date_is_an_error(self, engine):
        future = date.today() + timedelta(days=5)
        receipt = make_receipt(date=future.isoformat())
        engine.evaluate(receipt)
        assert flag(receipt, "FUTURE_DATE").severity == "error"
        assert flag(receipt, "FUTURE_DATE").message == f"The date {future:%d %b %Y} is in the future."

    @pytest.mark.parametrize(("justification", "severity"), [(None, "error"), ("Lost in transit", "warning")])
    def test_receipts_older_than_the_window_are_stale(self, engine, justification, severity):
        receipt = make_receipt(date=recent_weekday(120), justification=justification)
        engine.evaluate(receipt)
        assert flag(receipt, "STALE_RECEIPT").severity == severity
        assert "90-day submission window" in flag(receipt, "STALE_RECEIPT").message

    def test_receipt_exactly_at_the_age_limit_is_not_stale(self, engine):
        receipt = make_receipt(date=(date.today() - timedelta(days=90)).isoformat())
        engine.evaluate(receipt)
        assert "STALE_RECEIPT" not in codes(receipt)

    def test_weekend_expenses_are_noted(self, engine):
        receipt = make_receipt(date=recent_weekend_day())
        engine.evaluate(receipt)
        assert codes(receipt) == ["WEEKEND"] and flag(receipt, "WEEKEND").severity == "info"

    def test_weekend_note_can_be_switched_off(self, policy):
        engine = PolicyEngine(policy.model_copy(update={"weekend_expenses": "allow"}), "INR", 0.6)
        receipt = make_receipt(date=recent_weekend_day())
        engine.evaluate(receipt)
        assert codes(receipt) == []


class TestCurrency:
    def test_foreign_currency_is_converted_at_the_policy_rate(self, engine):
        receipt = make_receipt(total_amount=100.0, currency="usd", category="airfare")
        engine.evaluate(receipt)
        assert receipt.amount_in_base == receipt.reimbursable_amount == 8320.0
        assert flag(receipt, "FOREIGN_CURRENCY").message == "Converted to INR 8,320.00 at policy rate."

    def test_unknown_currency_cannot_be_converted(self, engine):
        receipt = make_receipt(currency="XYZ")
        engine.evaluate(receipt)
        assert flag(receipt, "UNKNOWN_CURRENCY").severity == "error"
        assert receipt.amount_in_base is None and receipt.reimbursable_amount is None

    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [(None, "INR", None), (100.0, None, 100.0), (100.0, "jpy", 56.0), (100.0, "XYZ", None)],
    )
    def test_to_base(self, engine, amount, currency, expected):
        assert engine._to_base(amount, currency) == expected


class TestNonReimbursableItems:
    def test_blocked_line_items_are_deducted(self, engine):
        receipt = make_receipt(
            vendor="Toit Brewpub", category="meals", total_amount=1848.0, business_purpose="Team dinner",
            line_items=[{"description": "Paneer Tikka", "amount": 420}, {"description": "Butter Chicken", "amount": 560},
                        {"description": "Craft Beer (2)", "amount": 780}],
        )
        engine.evaluate(receipt)
        assert receipt.amount_in_base == 1848.0
        assert receipt.reimbursable_amount == 1068.0
        assert flag(receipt, "NON_REIMBURSABLE_ITEMS").message.endswith("; they are deducted.")

    def test_deduction_is_converted_to_the_base_currency(self, engine):
        receipt = make_receipt(vendor="Hilton", category="lodging", total_amount=50.0, currency="USD",
                               line_items=[{"description": "Room", "amount": 40}, {"description": "Minibar", "amount": 10}])
        engine.evaluate(receipt)
        assert (receipt.amount_in_base, receipt.reimbursable_amount) == (4160.0, 3328.0)

    def test_blocked_word_in_description_is_flagged_without_a_deduction(self, engine):
        receipt = make_receipt(category="other", description="Wine tasting evening")
        engine.evaluate(receipt)
        assert flag(receipt, "NON_REIMBURSABLE_ITEMS").message == (
            "Contains non-reimbursable items (e.g. alcohol/tobacco).")
        assert receipt.reimbursable_amount == 450.0

    def test_blocked_items_without_amounts_are_flagged_only(self, engine):
        receipt = make_receipt(line_items=[LineItem(description="Beer")])
        engine.evaluate(receipt)
        assert "NON_REIMBURSABLE_ITEMS" in codes(receipt) and receipt.reimbursable_amount == 450.0

    def test_blocked_items_on_an_unconvertible_receipt_are_flagged_only(self, engine):
        receipt = make_receipt(currency="XYZ", line_items=[{"description": "Beer", "amount": 10}])
        engine.evaluate(receipt)
        assert {"UNKNOWN_CURRENCY", "NON_REIMBURSABLE_ITEMS"} <= set(codes(receipt))
        assert receipt.reimbursable_amount is None

    def test_blocked_keywords_match_whole_words_only(self, engine):
        receipt = make_receipt(line_items=[{"description": "Rumali Roti", "amount": 50},
                                           {"description": "Spanish Omelette", "amount": 150}])
        engine.evaluate(receipt)
        assert "NON_REIMBURSABLE_ITEMS" not in codes(receipt)


class TestLimits:
    def test_over_limit_amount_is_capped(self, engine):
        receipt = make_receipt(vendor="Taj MG Road", category="lodging", total_amount=17472.0)
        engine.evaluate(receipt)
        assert receipt.reimbursable_amount == 9000.0
        assert flag(receipt, "OVER_LIMIT").message == (
            "Exceeds the Hotel & Lodging limit of INR 9,000; reimbursement is capped.")

    def test_limit_is_checked_after_deducting_blocked_items(self, engine):
        receipt = make_receipt(category="meals", total_amount=2000.0, business_purpose="Team lunch",
                               line_items=[{"description": "Thali", "amount": 1300}, {"description": "Beer", "amount": 700}])
        engine.evaluate(receipt)
        assert receipt.reimbursable_amount == 1300.0 and "OVER_LIMIT" not in codes(receipt)

    def test_amount_at_the_limit_is_not_capped(self, engine):
        receipt = make_receipt(category="lodging", total_amount=9000.0)
        engine.evaluate(receipt)
        assert receipt.reimbursable_amount == 9000.0 and codes(receipt) == []


class TestDuplicatesAndConfidence:
    @pytest.mark.parametrize(("acknowledged", "flagged"), [(False, True), (True, False)])
    def test_possible_duplicate_until_acknowledged(self, engine, acknowledged, flagged):
        receipt = make_receipt(duplicate_of="rcpt-original", duplicate_acknowledged=acknowledged)
        engine.evaluate(receipt)
        assert ("POSSIBLE_DUPLICATE" in codes(receipt)) is flagged

    def test_low_confidence_fields_are_listed_in_reading_order(self, engine):
        receipt = make_receipt(confidence={"total_amount": 0.5, "date": 0.4, "vendor": 0.9})
        engine.evaluate(receipt)
        assert flag(receipt, "LOW_CONFIDENCE").message == "Low confidence on: total amount, date."

    def test_confirmed_or_empty_fields_are_not_low_confidence(self, engine):
        receipt = make_receipt(vendor=None, confidence={"total_amount": 0.5, "date": 0.4, "vendor": 0.1},
                               confirmed_fields=["date"])
        assert engine.low_confidence_fields(receipt) == ["total_amount"]

    def test_evaluate_replaces_previous_results(self, engine):
        receipt = make_receipt(category="lodging", total_amount=17472.0)
        engine.evaluate(receipt)
        receipt.data.total_amount = 5000.0
        engine.evaluate(receipt)
        assert codes(receipt) == [] and receipt.reimbursable_amount == 5000.0


@pytest.mark.parametrize(
    ("flags", "justification", "expected"),
    [
        (["OVER_LIMIT"], None, True),
        (["STALE_RECEIPT"], None, True),
        (["OVER_LIMIT"], "Conference hotel", False),
        (["WEEKEND", "LOW_CONFIDENCE"], None, False),
    ],
)
def test_needs_justification(engine, flags, justification, expected):
    receipt = make_receipt(justification=justification)
    receipt.flags = [Flag(code=c, severity="warning", message=c) for c in flags]
    assert engine.needs_justification(receipt) is expected


@pytest.mark.parametrize(
    ("a", "b", "days", "expected"),
    [
        ("2026-10-01", "2026-10-03", 2, True),
        ("2026-10-03", "2026-10-01", 2, True),
        ("2026-10-01", "2026-10-04", 2, False),
        ("2026-10-03T10:00:00", "2026-10-01", 2, True),
        (None, "2026-10-01", 2, False),
        ("garbage", "2026-10-01", 2, False),
    ],
)
def test_within_days(a, b, days, expected):
    assert PolicyEngine.within_days(a, b, days) is expected
