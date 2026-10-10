"""Deterministic sanity checks that drive the verification pass."""

from datetime import date, timedelta

import pytest

from app.models.domain import ExpenseData, LineItem
from app.services.extraction_checks import Issue, amounts_close, find_issues

TODAY = date(2026, 10, 10)


def clean(**overrides) -> ExpenseData:
    values = {"vendor": "Taj MG Road", "date": "2026-10-01", "total_amount": 1000.0, "currency": "INR"}
    values.update(overrides)
    return ExpenseData(**values)


def fields(issues: list[Issue]) -> list[str]:
    return [i.field for i in issues]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (100.0, 100.0, True),
        (10.0, 10.9, True),  # absolute floor of 1.0 for small amounts
        (10.0, 11.5, False),
        (0.0, 0.9, True),
        (1000.0, 1019.0, True),  # 2% of the reference amount for larger ones
        (1000.0, 1030.0, False),
    ],
)
def test_amounts_close(a, b, expected):
    assert amounts_close(a, b) is expected


def test_issue_is_an_immutable_value_object():
    issue = Issue("vendor", "msg")
    assert issue == Issue("vendor", "msg")
    with pytest.raises(AttributeError):
        issue.field = "date"  # type: ignore[misc]


def test_a_clean_extraction_has_no_issues():
    assert find_issues(clean(), today=TODAY) == []


def test_today_defaults_to_the_real_date():
    recent = (date.today() - timedelta(days=3)).isoformat()
    assert find_issues(clean(date=recent)) == []


class TestRequiredValues:
    def test_missing_vendor_total_and_date_are_each_reported(self):
        issues = find_issues(ExpenseData(), today=TODAY)
        assert fields(issues) == ["vendor", "total_amount", "date"]
        assert "Merchant name is missing" in issues[0].message

    def test_vendor_in_a_non_latin_script_must_be_transliterated(self):
        (issue,) = find_issues(clean(vendor="मनिष सर्विस सेंटर"), today=TODAY)
        assert issue.field == "vendor"
        assert "transliterated" in issue.message and "vendor_local" in issue.message


class TestDates:
    @pytest.mark.parametrize("value", ["2026-10-11", "2024-10-09"], ids=["future", "older-than-two-years"])
    def test_implausible_dates_are_questioned(self, value):
        (issue,) = find_issues(clean(date=value), today=TODAY)
        assert issue.field == "date"
        assert "looks wrong" in issue.message and "day-first" in issue.message

    @pytest.mark.parametrize("value", ["2026-10-10", "2024-10-11"], ids=["today", "just-inside-two-years"])
    def test_boundary_dates_are_accepted(self, value):
        assert find_issues(clean(date=value), today=TODAY) == []

    def test_unparseable_date(self):
        (issue,) = find_issues(clean(date="2026-02-30"), today=TODAY)
        assert issue == Issue("date", "Date '2026-02-30' is not a valid date.")


class TestLineItems:
    def test_line_items_that_add_up_raise_nothing(self):
        items = [LineItem(description="Room", amount=600.0), LineItem(description="Food", amount=400.0)]
        assert find_issues(clean(line_items=items), today=TODAY) == []

    def test_line_items_plus_tax_may_add_up_to_the_total(self):
        items = [LineItem(description="Plan", amount=999.0)]
        assert find_issues(clean(total_amount=1178.82, tax_amount=179.82, line_items=items), today=TODAY) == []

    def test_mismatched_sum_is_reported_with_both_figures(self):
        items = [LineItem(description="Room", amount=500.0)]
        (issue,) = find_issues(clean(line_items=items), today=TODAY)
        assert issue.field == "total_amount"
        assert "add up to 500.00 but the total is 1000.00" in issue.message

    def test_a_line_item_larger_than_the_total_is_reported(self):
        items = [LineItem(description="Room", amount=1500.0)]
        assert [i.message for i in find_issues(clean(line_items=items), today=TODAY)] == [
            "Line items add up to 1500.00 but the total is 1000.00. Only rows that actually contain "
            "handwritten/printed values are line items; quantity and rate are not amounts.",
            "A line item is larger than the total - re-check both.",
        ]

    def test_quantity_times_rate_mismatch_is_reported_when_totals_disagree(self):
        items = [LineItem(description="Diesel", quantity=10, unit_price=90.0, amount=500.0)]
        issues = find_issues(clean(line_items=items), today=TODAY)
        assert fields(issues) == ["total_amount", "total_amount"]
        assert "Line 'Diesel': 10.0 × 90.0 = 900.00, but its amount is 500.0" in issues[1].message

    def test_consistent_rows_are_not_blamed_when_only_the_total_is_off(self):
        items = [LineItem(description="Diesel", quantity=5, unit_price=100.0, amount=500.0)]
        (issue,) = find_issues(clean(line_items=items), today=TODAY)
        assert "add up to 500.00 but the total is 1000.00" in issue.message

    def test_quantity_slip_is_ignored_when_rows_already_add_up(self):
        items = [LineItem(description="Diesel", quantity=10, unit_price=90.0, amount=1000.0)]
        assert find_issues(clean(line_items=items), today=TODAY) == []

    def test_items_without_amounts_are_not_summed(self):
        items = [LineItem(description="Note", amount=None)]
        assert find_issues(clean(line_items=items), today=TODAY) == []

    def test_non_english_line_items_need_translation_reported_once(self):
        items = [LineItem(description="डीझेल", amount=500.0), LineItem(description="पेट्रोल", amount=500.0)]
        issues = find_issues(clean(line_items=items), today=TODAY)
        assert issues == [Issue("description", "Translate every line-item description to English.")]


class TestLocation:
    @pytest.mark.parametrize(
        "location",
        ["Shop 4, MG Road 560001", "Address: Mumbai", "A" * 41, "नवी मुंबई"],
        ids=["digits", "colon", "too-long", "non-latin"],
    )
    def test_whole_addresses_or_non_english_cities_are_rejected(self, location):
        (issue,) = find_issues(clean(location=location), today=TODAY)
        assert issue.field == "location"

    @pytest.mark.parametrize("location", ["Navi Mumbai", "Mahape, Navi Mumbai", None])
    def test_plain_city_names_are_fine(self, location):
        assert find_issues(clean(location=location), today=TODAY) == []
