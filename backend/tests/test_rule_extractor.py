"""Regex extraction from PDF text layers (offline engine and LLM gap filling)."""

import pytest

from app.services.rule_extractor import extract_with_rules, find_date, to_float

DINNER = "\n".join([
    "Toit Brewpub Indiranagar",
    "Bill No: TB-20931",
    "Date: 01/10/2026",
    "Paneer Tikka                  420.00",
    "Butter Chicken                560.00",
    "Craft Beer (2)                780.00",
    "Sub Total                    1,760.00",
    "GST 5%                         88.00",
    "Total Amount Rs. 1,848.00",
    "City: Bengaluru",
])


def fields_of(*lines: str) -> dict:
    return extract_with_rules("\n".join(lines))["fields"]


@pytest.mark.parametrize(("raw", "expected"), [("1,234.50", 1234.5), ("99", 99.0), ("abc", None), ("", None)])
def test_to_float(raw, expected):
    assert to_float(raw) == expected


class TestFindDate:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Date: 05/10/2026", "2026-10-05"),
            ("Dt. 05-10-2026", "2026-10-05"),
            ("05.10.2026", "2026-10-05"),
            ("Issued on 2026-10-05", "2026-10-05"),
            ("Date: 05/10/26", "2026-10-05"),
            ("5 Oct 2026", "2026-10-05"),
            ("5 October 2026", "2026-10-05"),
            ("05-Oct-2026", "2026-10-05"),
            ("5 Oct, 2026", "2026-10-05"),
            ("Oct 5, 2026", "2026-10-05"),
            ("October 5, 2026", "2026-10-05"),
        ],
    )
    def test_supported_formats_are_parsed_day_first(self, text, expected):
        assert find_date(text) == expected

    def test_skips_impossible_dates_and_uses_the_next_match(self):
        assert find_date("Printed 31/02/2026\nDate: 04/10/2026") == "2026-10-04"

    def test_first_valid_date_wins(self):
        assert find_date("Date: 03/10/2026\nDue: 30/10/2026") == "2026-10-03"

    @pytest.mark.parametrize("text", ["Thank you for visiting", "Room 1207   2 nights", ""])
    def test_returns_none_without_a_date(self, text):
        assert find_date(text) is None

    @pytest.mark.parametrize("text", ["Date: 05-10-26", "Date: 05.10.26"])
    def test_two_digit_years_with_dash_or_dot_separators(self, text):
        assert find_date(text) == "2026-10-05"


class TestTotal:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Grand Total INR 17,472.00", 17472.0),
            ("Total Amount Rs. 1,848.00", 1848.0),
            ("Amount Paid: 250.50", 250.5),
            ("Net Payable 99", 99.0),
            ("TOTAL         Rs. 270.00", 270.0),
            ("Total (incl. 5% GST) 1,848.00", 1848.0),  # the largest figure on the line is the total
        ],
    )
    def test_reads_the_total_from_a_labelled_line(self, line, expected):
        assert fields_of("Shop", line)["total_amount"] == expected

    @pytest.mark.parametrize("sub_total", ["Sub Total 1,760.00", "Subtotal 1,760.00", "SUB  TOTAL 1,760.00"])
    def test_sub_total_lines_are_ignored(self, sub_total):
        assert fields_of("Shop", sub_total, "Total Amount Rs. 1,848.00")["total_amount"] == 1848.0

    def test_a_total_heading_without_a_figure_is_skipped(self):
        assert fields_of("Shop", "TOTAL", "Grand Total 500.00")["total_amount"] == 500.0

    def test_no_total_label_means_no_total(self):
        assert fields_of("Shop", "Coffee   120.00")["total_amount"] is None

    @pytest.mark.parametrize(
        ("line", "field", "expected"),
        [
            ("Total Amount Rs. 1848.00", "total_amount", 1848.0),
            ("Grand Total 15600", "total_amount", 15600.0),
            ("IGST 18% 1250.50", "tax_amount", 1250.5),
        ],
    )
    def test_amounts_without_thousands_separators_are_read_in_full(self, line, field, expected):
        assert fields_of("Shop", "Date: 05/10/2026", line)[field] == expected


class TestTax:
    def test_sums_every_tax_line(self):
        assert fields_of("JioFiber", "CGST 9%                   89.91", "SGST 9%                   89.91")[
            "tax_amount"
        ] == pytest.approx(179.82)

    @pytest.mark.parametrize(("line", "expected"), [("IGST 5%   Rs. 301.50", 301.5), ("VAT 12.00", 12.0), ("Tax 5", 5.0)])
    def test_takes_the_last_amount_on_a_tax_line(self, line, expected):
        assert fields_of("Shop", line)["tax_amount"] == expected

    def test_tax_lines_without_amounts_are_ignored(self):
        assert fields_of("IndiGo", "Tax Invoice / Boarding Pass")["tax_amount"] is None


class TestLineItems:
    def test_rows_with_an_amount_become_line_items_but_totals_and_taxes_do_not(self):
        items = extract_with_rules(DINNER)["line_items"]
        assert items == [
            {"description": "Paneer Tikka", "amount": 420.0},
            {"description": "Butter Chicken", "amount": 560.0},
            {"description": "Craft Beer (2)", "amount": 780.0},
        ]

    def test_currency_prefix_is_allowed_and_fees_are_skipped(self):
        items = extract_with_rules(
            "Uber India\nTrip fare         Rs 742.30\nBooking Fee       Rs 20.00\nTolls             ₹ 85.00"
        )["line_items"]
        assert items == [{"description": "Trip fare", "amount": 742.3}, {"description": "Tolls", "amount": 85.0}]

    def test_first_line_is_the_vendor_not_an_item(self):
        assert extract_with_rules("Cafe Mocha     120.00\nLatte     120.00")["line_items"] == [
            {"description": "Latte", "amount": 120.0}
        ]

    def test_amount_needs_two_spaces_of_separation(self):
        assert extract_with_rules("Shop\nRoom 1207 nights 2")["line_items"] == []


class TestOtherFields:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Invoice No: 6E-INV-88213", "6E-INV-88213"),
            ("Bill No: TB-20931", "TB-20931"),
            ("Order No: SB-7781", "SB-7781"),
            ("Receipt # R-1234", "R-1234"),
            ("Invoice Number: INV/2026/001", "INV/2026/001"),
        ],
    )
    def test_invoice_number(self, line, expected):
        assert fields_of("Shop", line)["invoice_number"] == expected

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Paid via: Corporate Card", "Corporate Card"),
            ("Payment Mode: UPI", "UPI"),
            ("Paid by: Card", "Card"),
            ("Payment Method - Cash", "Cash"),
        ],
    )
    def test_payment_method(self, line, expected):
        assert fields_of("Shop", line)["payment_method"] == expected

    @pytest.mark.parametrize(("line", "expected"), [("City: Bengaluru", "Bengaluru"), ("Location - Navi Mumbai", "Navi Mumbai")])
    def test_location(self, line, expected):
        assert fields_of("Shop", line)["location"] == expected

    def test_vendor_is_the_first_line_truncated_to_80_chars(self):
        assert fields_of("  " + "A" * 100, "Total 10")["vendor"] == "A" * 80

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Total ₹ 490.00", "INR"),
            ("Total Rs 10", "INR"),
            ("Total INR 10", "INR"),
            ("Total $ 12.00", "USD"),
            ("Total USD 12", "USD"),
            ("Total € 9", "EUR"),
            ("Total EUR 9", "EUR"),
            ("Total £ 5", "GBP"),
            ("Total AED 40", "AED"),
            ("Total Dhs 40", "AED"),
            ("Total SGD 20", "SGD"),
            ("Total 20", None),
        ],
    )
    def test_currency_hints(self, line, expected):
        assert fields_of("Shop", line)["currency"] == expected

    def test_singapore_dollar_symbol_is_read_as_sgd(self):
        assert fields_of("Hawker Centre", "Date: 05/10/2026", "Total S$ 20.00")["currency"] == "SGD"


class TestExtractWithRules:
    @pytest.mark.parametrize("text", ["", "   \n  \n"])
    def test_empty_text_layer(self, text):
        assert extract_with_rules(text) == {
            "is_receipt": True,
            "fields": {},
            "confidence": {},
            "notes": "No text layer found - details need to be confirmed manually.",
        }

    def test_full_receipt(self):
        result = extract_with_rules(DINNER)
        assert result["is_receipt"] is True
        assert result["fields"] == {
            "vendor": "Toit Brewpub Indiranagar",
            "date": "2026-10-01",
            "total_amount": 1848.0,
            "currency": "INR",
            "tax_amount": 88.0,
            "invoice_number": "TB-20931",
            "payment_method": None,
            "location": "Bengaluru",
            "description": None,
            "category": None,
        }
        assert result["notes"] == "Extracted with the offline rules engine."

    def test_confidence_reflects_what_was_found(self):
        confidence = extract_with_rules(DINNER)["confidence"]
        assert confidence["total_amount"] == 0.85
        assert confidence["vendor"] == confidence["date"] == confidence["invoice_number"] == 0.7
        assert confidence["payment_method"] == confidence["description"] == confidence["category"] == 0.0

    def test_text_without_total_or_date_is_not_a_receipt(self):
        assert extract_with_rules("Meeting notes\nDiscuss the roadmap")["is_receipt"] is False

    @pytest.mark.parametrize("text", ["Shop\nTotal 10", "Shop\nDate: 05/10/2026"])
    def test_a_total_or_a_date_is_enough_to_be_a_receipt(self, text):
        assert extract_with_rules(text)["is_receipt"] is True
