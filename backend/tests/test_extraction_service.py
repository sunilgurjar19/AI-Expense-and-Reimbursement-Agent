"""ExtractionService: LLM extraction, review, verification pass, localisation and finalisation."""

import json

import pytest

from app.models.domain import ExpenseData, LineItem
from app.services.document_reader import DocumentContent
from app.services.extraction_checks import Issue
from app.services.extraction_service import (
    SYSTEM_PROMPT,
    UNRESOLVED_CONFIDENCE,
    ExtractionResult,
    ExtractionService,
    _looks_like_city,
    _reconcile_line_items,
    _unreadable_message,
)
from app.services.llm import ImagePart, LLMError, LLMResult
from tests.helpers import ScriptedRegistry, dmy, recent_weekday

BILL_DATE = recent_weekday(4)
PDF_TEXT = "\n".join([
    "Apollo Pharmacy",
    "Bill No: APL-90311",
    f"Date: {dmy(BILL_DATE)}",
    "Paracetamol 650mg x 2     64.00",
    "Vitamin D3 Sachet x 4     220.00",
    "Total Amount Rs. 284.00",
    "Payment Mode: UPI",
    "City: Mumbai",
])
IMAGE = ImagePart("image/jpeg", "aGVsbG8=")


def pdf_doc(text: str = PDF_TEXT) -> DocumentContent:
    return DocumentContent(kind="pdf", text=text, images=[IMAGE], pdf_b64="JVBERi0xLjQ=")


def photo_doc() -> DocumentContent:
    return DocumentContent(kind="image", images=[IMAGE])


def model_reply(language: str = "English", line_items: list | None = None, notes: str | None = None, **fields) -> dict:
    values = {
        "vendor": "Apollo Pharmacy",
        "date": BILL_DATE,
        "total_amount": 284,
        "currency": "INR",
        "category": "medical",
        "invoice_number": "APL-90311",
        "location": "Mumbai",
        "description": "Medicines",
    }
    values.update(fields)
    return {
        "is_receipt": True,
        "language": language,
        "fields": values,
        "confidence": {k: 0.95 for k, v in values.items() if v is not None},
        "line_items": line_items or [],
        "notes": notes,
    }


def result_with(source: str = "fake", **data) -> ExtractionResult:
    return ExtractionResult(data=ExpenseData(**data), confidence={k: 0.95 for k in data}, source=source)


@pytest.fixture
def make_service(policy):
    def factory(replies=None, verify_mode="auto", **registry_kwargs):
        registry = ScriptedRegistry(replies, **registry_kwargs)
        return ExtractionService(registry, policy, "INR", verify_mode), registry

    return factory


# --------------------------------------------------------------------- extract


class TestExtract:
    async def test_request_carries_the_document_categories_and_text_layer(self, make_service):
        service, registry = make_service({"extract_receipt": model_reply()})
        await service.extract(pdf_doc(), "apollo.pdf")

        (request,) = registry.requests
        assert request.task == "extract_receipt"
        assert request.system == SYSTEM_PROMPT
        assert request.images == [IMAGE] and request.pdf_b64 == "JVBERi0xLjQ="
        assert request.context == {"text": PDF_TEXT, "file_name": "apollo.pdf", "zoom": False}
        assert '- "lodging" = Hotel & Lodging' in request.prompt
        assert 'default currency is INR. File name: "apollo.pdf"' in request.prompt
        assert "Text layer extracted from the PDF" in request.prompt and "Vitamin D3 Sachet" in request.prompt

    async def test_photos_ask_for_zoomed_tiles_and_have_no_text_block(self, make_service):
        service, registry = make_service({"extract_receipt": model_reply()})
        await service.extract(photo_doc(), "chai.jpg")
        (request,) = registry.requests
        assert request.context["zoom"] is True
        assert "Text layer extracted" not in request.prompt

    async def test_model_values_are_normalised(self, make_service):
        reply = model_reply(
            vendor="  Apollo Pharmacy ",
            date="2026-01-02",  # a wrong month/day swap by the model ...
            date_as_printed=dmy(BILL_DATE),  # ... loses to our own day-first parse of the printed date
            total_amount="Rs. 284.00",
            currency="₹",
            category="Medical Reimbursement",  # a label instead of the key
            invoice_number="0 14821",
            payment_method="null",
        )
        service, _ = make_service({"extract_receipt": reply})
        result = await service.extract(photo_doc(), "apollo.jpg")

        assert result.data.model_dump(include={"vendor", "date", "total_amount", "currency", "category",
                                               "invoice_number", "payment_method"}) == {
            "vendor": "Apollo Pharmacy",
            "date": BILL_DATE,
            "total_amount": 284.0,
            "currency": "INR",
            "category": "medical",
            "invoice_number": "014821",
            "payment_method": None,
        }
        assert result.source == "fake" and result.fell_back is False and result.read_warning is None
        assert result.confidence["total_amount"] == 0.95

    async def test_text_layer_fills_fields_the_model_missed(self, make_service):
        reply = model_reply(date=None, total_amount=None, currency=None, invoice_number=None, location=None)
        service, _ = make_service({"extract_receipt": reply})
        result = await service.extract(pdf_doc(), "apollo.pdf")

        assert (result.data.date, result.data.total_amount, result.data.currency) == (BILL_DATE, 284.0, "INR")
        assert (result.data.invoice_number, result.data.location) == ("APL-90311", "Mumbai")
        assert result.confidence["total_amount"] == 0.7  # capped: the text layer is only a fallback
        assert result.confidence["vendor"] == 0.95
        assert [i.description for i in result.data.line_items] == ["Paracetamol 650mg x 2", "Vitamin D3 Sachet x 4"]
        assert result.notes == "Filled date, total_amount, currency, invoice_number, location from the PDF text."

    async def test_gap_filling_never_overrides_what_the_model_read(self, make_service):
        service, _ = make_service({"extract_receipt": model_reply(total_amount=300, notes="Faded print")})
        result = await service.extract(pdf_doc(), "apollo.pdf")
        assert result.data.total_amount == 300.0
        assert result.notes == "Faded print"

    async def test_line_items_read_by_the_model_are_not_replaced_by_text_layer_rows(self, make_service):
        reply = model_reply(location=None, line_items=[{"description": "Medicines", "amount": 284}])
        service, _ = make_service({"extract_receipt": reply})
        result = await service.extract(pdf_doc(), "apollo.pdf")
        assert [i.description for i in result.data.line_items] == ["Medicines"]
        assert result.data.location == "Mumbai"  # other gaps are still filled

    async def test_mock_provider_results_are_not_gap_filled(self, make_service):
        service, _ = make_service({"extract_receipt": model_reply(location=None)}, provider="mock")
        result = await service.extract(pdf_doc(), "apollo.pdf")
        assert result.data.location is None
        assert result.read_warning is None  # it had a text layer to read

    @pytest.mark.parametrize(
        ("fell_back", "errors", "expected"),
        [
            (False, [], "The offline rules engine is active"),
            (True, ["ollama: Ollama request failed: ConnectError('refused')"],
             "couldn't read this photo/scan (Ollama request failed: ConnectError('refused'))"),
        ],
    )
    async def test_offline_engine_on_a_photo_explains_why_nothing_was_read(self, make_service, fell_back, errors,
                                                                          expected):
        service, _ = make_service({"extract_receipt": {"fields": {}}}, provider="mock", fell_back=fell_back,
                                  errors=errors)
        result = await service.extract(photo_doc(), "chai.jpg")
        assert expected in result.read_warning

    async def test_llm_failure_propagates_to_the_caller(self, make_service):
        service, _ = make_service({"extract_receipt": LLMError("all providers failed")})
        with pytest.raises(LLMError, match="all providers failed"):
            await service.extract(pdf_doc(), "apollo.pdf")


@pytest.mark.parametrize(
    ("fell_back", "errors", "expected"),
    [
        (False, [], "The offline rules engine is active - it can only read PDFs with a text layer"),
        (True, [], "couldn't read this photo/scan (it did not respond)"),
        (True, ["claude: " + "x" * 300], "(" + "x" * 140 + ")"),  # long reasons are truncated
    ],
)
def test_unreadable_message(fell_back, errors, expected):
    assert expected in _unreadable_message(fell_back, errors)


# --------------------------------------------------------------- review/verify


class TestShouldVerify:
    @pytest.mark.parametrize(
        ("mode", "source", "document", "data", "issues", "expected"),
        [
            ("auto", "fake", "pdf", {"language": "English"}, [], False),
            ("auto", "fake", "pdf", {"language": "en"}, [], False),
            ("auto", "fake", "pdf", {}, [], False),  # unknown language counts as English
            ("auto", "fake", "pdf", {}, [Issue("total_amount", "x")], True),
            ("auto", "fake", "photo", {"language": "Hindi"}, [], True),
            ("auto", "fake", "pdf", {"vendor_local": "अपोलो"}, [], True),
            ("always", "fake", "pdf", {"language": "English"}, [], True),
            ("off", "fake", "pdf", {"language": "Hindi"}, [Issue("date", "x")], False),
            ("always", "mock", "pdf", {}, [Issue("date", "x")], False),  # the rules engine can't re-read
            ("always", "fake", "empty", {}, [Issue("date", "x")], False),  # nothing to look at again
        ],
    )
    def test_decision(self, make_service, mode, source, document, data, issues, expected):
        service, _ = make_service(verify_mode=mode)
        doc = {"pdf": pdf_doc(), "photo": photo_doc(), "empty": DocumentContent(kind="image")}[document]
        assert service.should_verify(result_with(source, **data), issues, doc) is expected


def test_review_runs_the_deterministic_checks(make_service):
    service, _ = make_service()
    issues = service.review(result_with(total_amount=10.0, date=BILL_DATE))
    assert [i.field for i in issues] == ["vendor"]


class TestVerify:
    @staticmethod
    def draft_with_wrong_total() -> ExtractionResult:
        items = [LineItem(description="Paracetamol", amount=64.0), LineItem(description="Vitamin D3", amount=220.0)]
        return ExtractionResult(
            data=ExpenseData(vendor="Apollo Pharmacy", date=BILL_DATE, total_amount=500.0, currency="INR",
                             invoice_number="APL-90311", vendor_local="अपोलो फार्मेसी", language="Hindi",
                             line_items=items),
            confidence={"vendor": 0.9, "total_amount": 0.9, "invoice_number": 0.65},
            notes="Handwritten",
            source="fake",
            address_local="महापे, नवी मुंबई",
        )

    async def test_corrected_reading_replaces_the_draft_when_it_passes_more_checks(self, make_service):
        draft = self.draft_with_wrong_total()
        issues = make_service()[0].review(draft)
        reply = model_reply(total_amount=284, line_items=[{"description": "Paracetamol", "amount": 64},
                                                           {"description": "Vitamin D3", "amount": 220}])
        service, registry = make_service({"verify_receipt": reply})

        checked = await service.verify(photo_doc(), "apollo.jpg", draft, issues)

        assert checked is not draft and checked.verified is True
        assert checked.data.total_amount == 284.0 and service.review(checked) == []
        (request,) = registry.requests
        assert request.task == "verify_receipt"
        assert "Line items add up to 284.00 but the total is 500.00" in request.prompt
        assert '"total_amount": 500.0' in request.prompt  # the draft is shown to the model
        assert request.context["draft"]["fields"]["total_amount"] == 500.0
        assert request.context["zoom"] is True

    async def test_fields_only_the_first_pass_found_are_kept(self, make_service):
        draft = self.draft_with_wrong_total()
        reply = model_reply(total_amount=284, invoice_number=None, language=None)
        reply["line_items"] = [{"description": "Paracetamol", "amount": 64}, {"description": "Vitamin D3", "amount": 220}]
        service, _ = make_service({"verify_receipt": reply})

        checked = await service.verify(photo_doc(), "apollo.jpg", draft, service.review(draft))

        assert checked.data.invoice_number == "APL-90311"
        assert checked.confidence["invoice_number"] == 0.65  # with the first pass's confidence
        assert (checked.data.vendor_local, checked.data.language) == ("अपोलो फार्मेसी", "Hindi")
        assert checked.address_local == "महापे, नवी मुंबई"

    async def test_worse_second_reading_is_discarded(self, make_service):
        draft = self.draft_with_wrong_total()
        reply = model_reply(vendor="अपोलो फार्मेसी", total_amount=999, date="2020-01-01")
        service, _ = make_service({"verify_receipt": reply})
        assert await service.verify(photo_doc(), "apollo.jpg", draft, service.review(draft)) is draft

    @pytest.mark.parametrize(
        "reply",
        [LLMError("timeout"), LLMResult(text="{}", provider="mock", fell_back=True)],
        ids=["provider-error", "fell-back-to-rules-engine"],
    )
    async def test_draft_is_kept_when_no_real_second_reading_happens(self, make_service, reply):
        draft = self.draft_with_wrong_total()
        service, _ = make_service({"verify_receipt": reply})
        assert await service.verify(photo_doc(), "apollo.jpg", draft, service.review(draft)) is draft

    async def test_non_english_documents_get_a_generic_recheck_instruction(self, make_service):
        service, registry = make_service({"verify_receipt": model_reply()})
        draft = result_with(vendor="Apollo Pharmacy", date=BILL_DATE, total_amount=284.0, language="Marathi")
        await service.verify(photo_doc(), "memo.jpg", draft, [])
        assert "No arithmetic problems found, but this is a non-English" in registry.requests[0].prompt

    async def test_text_layer_also_fills_gaps_after_verification(self, make_service):
        service, _ = make_service({"verify_receipt": model_reply(invoice_number=None, location=None)})
        draft = result_with(vendor="Apollo Pharmacy", date=BILL_DATE, total_amount=284.0, language="Hindi")
        checked = await service.verify(pdf_doc(), "apollo.pdf", draft, [])
        assert (checked.data.invoice_number, checked.data.location) == ("APL-90311", "Mumbai")


# -------------------------------------------------------------------- localise


class TestLocalise:
    @staticmethod
    def marathi_memo(**overrides) -> ExtractionResult:
        data = {
            "vendor": "Manish Service Center",
            "language": "Marathi",
            "description": "डीझेल खरेदी",
            "location": None,
            "line_items": [LineItem(description="डीझेल", amount=500.0), LineItem(description="Engine Oil", amount=80.0)],
        }
        data.update(overrides)
        return ExtractionResult(data=ExpenseData(**data), address_local="महापे, नवी मुंबई")

    async def test_translates_items_description_and_city(self, make_service):
        reply = {"item_0": "Diesel", "description": "Diesel purchase", "address": "Mahape, Navi Mumbai"}
        service, registry = make_service({"translate_fields": reply})
        result = await service.localise(self.marathi_memo())

        assert [i.description for i in result.data.line_items] == ["Diesel", "Engine Oil"]
        assert (result.data.description, result.data.location) == ("Diesel purchase", "Mahape, Navi Mumbai")
        (request,) = registry.requests
        assert request.task == "translate_fields" and "Marathi receipt" in request.prompt
        assert json.loads(request.prompt.split("\n\n")[1]) == {
            "item_0": "डीझेल",
            "description": "डीझेल खरेदी",
            "address": "महापे, नवी मुंबई",
        }

    async def test_unusable_translations_are_ignored(self, make_service):
        reply = {"item_0": "डीझेल", "item_9": "Ghost", "item_x": "Bad key", "description": "  ",
                 "address": "Shop 4, Plot 12, MIDC 400710", "unexpected": "value"}
        service, _ = make_service({"translate_fields": reply})
        result = await service.localise(self.marathi_memo())
        assert [i.description for i in result.data.line_items] == ["डीझेल", "Engine Oil"]
        assert (result.data.description, result.data.location) == ("डीझेल खरेदी", None)

    async def test_address_like_location_is_reduced_to_a_city(self, make_service):
        service, registry = make_service({"translate_fields": {"address": "Navi Mumbai"}})
        extraction = ExtractionResult(data=ExpenseData(location="Plot 12, MIDC, Navi Mumbai 400710"))
        result = await service.localise(extraction)
        assert result.data.location == "Navi Mumbai"
        assert "Plot 12, MIDC" in registry.requests[0].prompt

    async def test_english_receipts_need_no_translation_call(self, make_service):
        service, registry = make_service()
        extraction = ExtractionResult(data=ExpenseData(vendor="Starbucks", location="Bengaluru",
                                                       line_items=[LineItem(description="Latte", amount=310.0)]))
        assert await service.localise(extraction) is extraction
        assert registry.requests == []

    async def test_translation_failure_leaves_values_untouched(self, make_service):
        service, _ = make_service({"translate_fields": LLMError("offline")})
        result = await service.localise(self.marathi_memo())
        assert result.data.description == "डीझेल खरेदी"


# -------------------------------------------------------------------- finalise


class TestFinalise:
    @staticmethod
    def extraction(**kwargs) -> ExtractionResult:
        items = [LineItem(description="Paracetamol", amount=64.0), LineItem(description="Vitamin D3", amount=220.0)]
        data = ExpenseData(vendor=None, date=BILL_DATE, total_amount=500.0, currency="INR", line_items=items)
        return ExtractionResult(data=data, confidence={"total_amount": 0.95, "date": 0.9}, **kwargs)

    def test_unresolved_issues_lower_confidence_of_populated_fields(self, make_service):
        service, _ = make_service()
        result = service.finalise(self.extraction())
        assert [i.field for i in result.issues] == ["vendor", "total_amount"]
        assert result.confidence == {"total_amount": UNRESOLVED_CONFIDENCE, "date": 0.9}  # vendor is empty

    def test_existing_lower_confidence_is_kept(self, make_service):
        service, _ = make_service()
        extraction = self.extraction()
        extraction.confidence["total_amount"] = 0.3
        assert service.finalise(extraction).confidence["total_amount"] == 0.3

    def test_notes_summarise_verification_and_the_first_two_issues(self, make_service):
        service, _ = make_service()
        result = service.finalise(self.extraction(notes="Handwritten.", verified=True))
        assert result.notes.startswith(
            "Handwritten. Double-checked by a second reading. Please confirm: Merchant name is missing "
            "Line items add up to 284.00 but the total is 500.00."
        )

    def test_clean_extraction_keeps_confidence_and_has_no_notes(self, make_service):
        service, _ = make_service()
        extraction = result_with(vendor="Apollo Pharmacy", date=BILL_DATE, total_amount=284.0)
        result = service.finalise(extraction)
        assert result.issues == [] and result.notes is None
        assert result.confidence == {"vendor": 0.95, "date": 0.95, "total_amount": 0.95}


# ------------------------------------------------------------------- normalise


class TestNormalise:
    def test_flat_payload_without_a_fields_object(self, make_service):
        service, _ = make_service()
        result = service._normalise({"vendor": "Cafe", "total_amount": "120", "currency": "usd"}, "fake", False)
        assert (result.data.vendor, result.data.total_amount, result.data.currency) == ("Cafe", 120.0, "USD")

    def test_line_items_are_cleaned(self, make_service):
        service, _ = make_service()
        payload = {"fields": {"total_amount": 250}, "line_items": [
            "not a dict",
            {"description": "null", "amount": 5},
            {"description": "Empty row"},
            {"description": "Chai", "quantity": "2", "unit_price": "60"},
            {"description": " Sandwich ", "amount": "Rs. 130"},
        ]}
        items = service._normalise(payload, "fake", False).data.line_items
        assert [i.model_dump() for i in items] == [
            {"description": "Chai", "amount": 120.0, "quantity": 2.0, "unit_price": 60.0},
            {"description": "Sandwich", "amount": 130.0, "quantity": None, "unit_price": None},
        ]

    def test_total_is_derived_from_line_items_only_when_every_amount_is_known(self, make_service):
        service, _ = make_service()
        complete = {"line_items": [{"description": "A", "amount": 10.5}, {"description": "B", "amount": 4.25}]}
        partial = {"line_items": [{"description": "A", "amount": 10.5}, {"description": "B", "quantity": 2}]}
        assert service._normalise(complete, "fake", False).data.total_amount == 14.75
        assert service._normalise(partial, "fake", False).data.total_amount is None

    @pytest.mark.parametrize(("total", "currency"), [(100, "INR"), (None, None)])
    def test_base_currency_is_assumed_only_when_there_is_a_total(self, make_service, total, currency):
        service, _ = make_service()
        assert service._normalise({"fields": {"total_amount": total}}, "fake", False).data.currency == currency

    def test_vendor_local_identical_to_vendor_is_dropped(self, make_service):
        service, _ = make_service()
        data = service._normalise({"fields": {"vendor": "Taj", "vendor_local": "Taj"}}, "fake", False).data
        assert data.vendor_local is None

    def test_confidence_is_clamped_and_defaulted_for_populated_fields(self, make_service):
        service, _ = make_service()
        payload = {
            "fields": {"vendor": "Taj", "date": "2026-10-01", "total_amount": 10, "location": "Pune", "tax_amount": None},
            "confidence": {"vendor": 1.7, "date": -0.2, "total_amount": "high", "tax_amount": 0.4},
        }
        confidence = service._normalise(payload, "fake", False).confidence
        assert confidence == {"vendor": 1.0, "date": 0.0, "total_amount": 0.8, "currency": 0.8, "location": 0.8}

    def test_metadata_fields(self, make_service):
        service, _ = make_service()
        payload = {"is_receipt": False, "notes": "null", "fields": {"language": "Hindi", "address_as_printed": "महापे"}}
        result = service._normalise(payload, "ollama", True)
        assert (result.is_receipt, result.notes, result.source, result.fell_back) == (False, None, "ollama", True)
        assert (result.data.language, result.address_local) == ("Hindi", "महापे")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("lodging", "lodging"), ("Hotel & Lodging", "lodging"), ("client entertainment", "client_entertainment"),
         ("CLIENT_ENTERTAINMENT", "client_entertainment"), ("groceries", None), ("null", None)],
    )
    def test_category_accepts_keys_or_labels(self, make_service, value, expected):
        service, _ = make_service()
        assert service._normalise({"fields": {"category": value}}, "fake", False).data.category == expected

    @pytest.mark.parametrize(
        "payload",
        [{"fields": {"vendor": "Cafe", "total_amount": 120}, "confidence": 0.9},
         {"fields": [["vendor", "Cafe"]], "vendor": "Cafe", "total_amount": 120}],
        ids=["scalar-confidence", "list-fields"],
    )
    def test_non_object_confidence_or_fields_from_the_model_are_tolerated(self, make_service, payload):
        service, _ = make_service()
        result = service._normalise(payload, "fake", False)
        assert result.data.vendor == "Cafe" and result.data.total_amount == 120.0
        assert all(0.0 <= c <= 1.0 for c in result.confidence.values())


class TestReconcileLineItems:
    @staticmethod
    def items(*rows) -> list[LineItem]:
        return [LineItem(description=d, quantity=q, unit_price=u, amount=a) for d, q, u, a in rows]

    def test_row_total_misread_as_unit_rate_is_corrected(self):
        items = self.items(("Paracetamol x 2", 2, 64.0, 128.0), ("Vitamin D3 x 4", 4, 220.0, 880.0))
        _reconcile_line_items(items, 284.0)
        assert [(i.unit_price, i.amount) for i in items] == [(32.0, 64.0), (55.0, 220.0)]

    @pytest.mark.parametrize(
        ("rows", "total"),
        [
            ([("Chai", 2, 60.0, 120.0)], 120.0),  # already consistent
            ([("Chai", 2, None, 120.0)], 60.0),  # a missing rate: nothing to reason about
            ([("Chai", 2, 60.0, 120.0)], 999.0),  # neither interpretation matches
            ([("Chai", 2, 60.0, 120.0)], None),
            ([], 100.0),
        ],
    )
    def test_left_alone_when_the_fix_does_not_apply(self, rows, total):
        items = self.items(*rows)
        before = [i.model_dump() for i in items]
        _reconcile_line_items(items, total)
        assert [i.model_dump() for i in items] == before

    def test_zero_quantity_leaves_rate_empty(self):
        items = self.items(("Service", 0, 100.0, 50.0))
        _reconcile_line_items(items, 100.0)
        assert (items[0].amount, items[0].unit_price) == (100.0, None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Navi Mumbai", True), ("Mahape, Navi Mumbai", True), (None, False), ("", False), ("नवी मुंबई", False),
     ("Plot 12, MIDC", False), ("Address: Pune", False), ("x" * 41, False)],
)
def test_looks_like_city(value, expected):
    assert _looks_like_city(value) is expected
