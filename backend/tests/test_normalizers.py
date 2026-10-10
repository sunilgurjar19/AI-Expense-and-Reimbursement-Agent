"""Coercion of loosely-typed model output into clean values."""

import logging

import pytest

from app.services.normalizers import (
    ascii_digits,
    clean_str,
    has_non_latin_letters,
    normalise_currency,
    normalise_date,
    normalise_reference,
    parse_json_object,
    to_amount,
)


class TestParseJsonObject:
    @pytest.mark.parametrize(
        "text",
        [
            '{"vendor": "Taj", "total": 10}',
            '```json\n{"vendor": "Taj", "total": 10}\n```',
            '```\n{"vendor": "Taj", "total": 10}\n```',
            'Sure! Here is the data: {"vendor": "Taj", "total": 10} Hope that helps.',
            '  \n{"vendor": "Taj", "total": 10}\n  ',
        ],
        ids=["plain", "json-fence", "bare-fence", "surrounded-by-prose", "whitespace"],
    )
    def test_extracts_the_object_from_common_model_wrappings(self, text):
        assert parse_json_object(text) == {"vendor": "Taj", "total": 10}

    def test_keeps_nested_structures(self):
        assert parse_json_object('{"fields": {"vendor": "X"}, "line_items": [{"a": 1}]}') == {
            "fields": {"vendor": "X"},
            "line_items": [{"a": 1}],
        }

    @pytest.mark.parametrize("text", ["[1, 2, 3]", '"just a string"', "42", "null"])
    def test_returns_empty_dict_for_json_that_is_not_an_object(self, text):
        assert parse_json_object(text) == {}

    @pytest.mark.parametrize("text", ["", "no json here", "{ unterminated", "[1, 2"])
    def test_returns_empty_dict_when_nothing_parses(self, text):
        assert parse_json_object(text) == {}

    def test_logs_a_warning_when_braces_contain_invalid_json(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.services.normalizers"):
            assert parse_json_object("prefix {vendor: 'single quotes'} suffix") == {}
        assert "invalid JSON" in caplog.text


class TestCleanStr:
    @pytest.mark.parametrize("value", [None, "", "   ", "null", "NULL", "None", "n/a", "N/A", "unknown", " Unknown "])
    def test_null_like_values_become_none(self, value):
        assert clean_str(value) is None

    @pytest.mark.parametrize(("value", "expected"), [("  Taj Hotel ", "Taj Hotel"), (0, "0"), (12.5, "12.5")])
    def test_other_values_are_stringified_and_trimmed(self, value, expected):
        assert clean_str(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("२०२६", "2026"),  # Devanagari
        ("২০২৬", "2026"),  # Bengali
        ("૨૦૨૬", "2026"),  # Gujarati
        ("௨௦௨௬", "2026"),  # Tamil
        ("೨೦೨೬", "2026"),  # Kannada
        ("Bill ४५", "Bill 45"),
        ("12/05", "12/05"),
    ],
)
def test_ascii_digits_translates_indic_numerals(text, expected):
    assert ascii_digits(text) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),  # booleans are not amounts
        (False, None),
        (12, 12.0),
        (12.346, 12.35),
        ("Rs. 1,234.50", 1234.5),
        ("₹ 15600.00", 15600.0),
        ("INR 17,472", 17472.0),
        ("-50", -50.0),
        ("१२३४.५", 1234.5),
        ("no digits", None),
        ("", None),
    ],
)
def test_to_amount(value, expected):
    assert to_amount(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("₹", "INR"),
        ("Rs", "INR"),
        ("rs.", "INR"),
        ("Rupees", "INR"),
        ("रु", "INR"),
        ("रु.", "INR"),
        ("$", "USD"),
        ("€", "EUR"),
        ("£", "GBP"),
        ("usd", "USD"),
        ("Euro", "EUR"),  # first three letters of an alphabetic code
        (" sgd ", "SGD"),
        ("US$", None),
        ("क", None),
        ("null", None),
        (None, None),
    ],
)
def test_normalise_currency(value, expected):
    assert normalise_currency(value) == expected


class TestNormaliseDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-10-05", "2026-10-05"),
            ("2026-10-05T18:30:00Z", "2026-10-05"),
            ("05/10/2026", "2026-10-05"),  # day first, as on Indian bills
            ("05-10-2026", "2026-10-05"),
            ("05.10.2026", "2026-10-05"),
            ("05/10/26", "2026-10-05"),
            ("05-10-26", "2026-10-05"),
            ("05.10.26", "2026-10-05"),
            ("5 Oct 2026", "2026-10-05"),
            ("5 October 2026", "2026-10-05"),
            ("05-Oct-2026", "2026-10-05"),
            ("5 Oct 26", "2026-10-05"),
            ("Oct 5, 2026", "2026-10-05"),
            ("October 5, 2026", "2026-10-05"),
            ("२०/०९/२६", "2026-09-20"),  # Devanagari digits
        ],
    )
    def test_parses_iso_and_day_first_formats(self, value, expected):
        assert normalise_date(value) == expected

    @pytest.mark.parametrize("value", [None, "", "null", "31/02/2026", "2026-13-01", "12/31/2026", "yesterday"])
    def test_rejects_invalid_or_ambiguous_values(self, value):
        assert normalise_date(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0 14821", "014821"),  # spaces inside a pure number are an OCR artefact
        (" 12 34 ", "1234"),
        ("२०२६/१२", "2026/12"),
        ("12 / 34", "12/34"),
        ("INV 001", "INV 001"),  # alphanumeric references keep their spacing
        ("TAJ-BLR-44109", "TAJ-BLR-44109"),
        ("null", None),
        (None, None),
    ],
)
def test_normalise_reference(value, expected):
    assert normalise_reference(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Café Coffee Day", False),  # Latin-1 accents still count as Latin
        ("Łódź", False),  # Latin Extended-A
        ("मनिष सर्विस सेंटर", True),
        ("Manish सर्विस", True),
        ("தமிழ்", True),
        ("12345", False),
        ("", False),
        (None, False),
    ],
)
def test_has_non_latin_letters(text, expected):
    assert has_non_latin_letters(text) is expected
