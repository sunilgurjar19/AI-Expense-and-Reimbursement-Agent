"""PurposeService: LLM-written claim remarks with a deterministic fallback."""

import json

import pytest

from app.models.domain import ReceiptStage, User
from app.services.llm import LLMError
from app.services.purpose_service import MAX_LENGTH, PurposeService, _mentions_person
from tests.helpers import ScriptedRegistry, make_claim, make_receipt

EMPLOYEE = User(id="u-1001", username="employee", password="-", name="Aarav Sharma", email="a@acme.example",
                role="employee", department="Product Engineering", employee_code="EMP-1001")


def trip_claim():
    return make_claim(
        make_receipt(vendor="IndiGo Airlines", category="airfare", date="2026-10-01", location="Mumbai",
                     line_items=[{"description": f"Item {n}", "amount": 1} for n in range(7)]),
        make_receipt(vendor="Taj MG Road", category="lodging", date="2026-10-03", location="MG Road, bengaluru"),
        make_receipt(vendor="Uber India", category="local_conveyance", date="2026-10-02", location="Bengaluru"),
        period_start="2026-10-01",
        period_end="2026-10-03",
    )


TRIP_SUMMARY = "Business trip to Bengaluru, 1-3 Oct 2026 - airfare, hotel & lodging and local conveyance & toll tax."


@pytest.fixture
def make_service(policy):
    def factory(reply=None):
        registry = ScriptedRegistry({"infer_purpose": reply} if reply is not None else {})
        return PurposeService(registry, policy), registry

    return factory


class TestInfer:
    async def test_without_readable_receipts_there_is_nothing_to_infer(self, make_service):
        service, registry = make_service()
        claim = make_claim(make_receipt(vendor=None, category=None), make_receipt(stage=ReceiptStage.EXTRACTING),
                           make_receipt(excluded=True))
        assert await service.infer(claim, EMPLOYEE) is None
        assert registry.requests == []

    async def test_model_wording_is_used_without_wrapping_quotes(self, make_service):
        service, _ = make_service({"purpose": ' "Client workshop in Bengaluru, 1-3 Oct 2026." '})
        assert await service.infer(trip_claim(), EMPLOYEE) == "Client workshop in Bengaluru, 1-3 Oct 2026."

    async def test_request_describes_the_receipts_and_the_draft(self, make_service):
        service, registry = make_service({"purpose": "x"})
        await service.infer(trip_claim(), EMPLOYEE)

        (request,) = registry.requests
        assert request.task == "infer_purpose"
        assert request.context == {"fallback": TRIP_SUMMARY}
        assert "Department: Product Engineering" in request.prompt
        assert f'"{TRIP_SUMMARY}"' in request.prompt
        receipts = json.loads(request.prompt.split("Receipts on this claim:\n")[1].split("\n")[0])
        assert receipts[0] == {"merchant": "IndiGo Airlines", "category": "Airfare", "date": "2026-10-01",
                               "city": "Mumbai", "items": ["Item 0", "Item 1", "Item 2", "Item 3", "Item 4"]}
        assert [r["category"] for r in receipts] == ["Airfare", "Hotel & Lodging", "Local Conveyance & Toll Tax"]

    async def test_text_naming_the_employee_is_discarded_for_the_summary(self, make_service):
        service, _ = make_service({"purpose": "Aarav's trip to Bengaluru for a workshop"})
        assert await service.infer(trip_claim(), EMPLOYEE) == TRIP_SUMMARY

    @pytest.mark.parametrize("reply", [LLMError("offline"), "not json at all", {"purpose": None}, {"purpose": "null"},
                                       {"something": "else"}])
    async def test_failed_or_empty_inference_falls_back_to_the_summary(self, make_service, reply):
        service, _ = make_service(reply)
        assert await service.infer(trip_claim(), EMPLOYEE) == TRIP_SUMMARY

    async def test_long_purposes_are_truncated(self, make_service):
        service, _ = make_service({"purpose": "Workshop " * 50})
        assert len(await service.infer(trip_claim(), EMPLOYEE)) == MAX_LENGTH

    async def test_works_without_an_employee_record(self, make_service):
        service, registry = make_service({"purpose": "Aarav's offsite"})
        assert await service.infer(trip_claim(), None) == "Aarav's offsite"  # nobody to check against
        assert "Department: \n" in registry.requests[0].prompt

    async def test_returns_none_when_neither_model_nor_summary_has_anything(self, make_service):
        service, _ = make_service({"purpose": ""})
        claim = make_claim(make_receipt(vendor="Some Shop", category=None))
        assert await service.infer(claim, EMPLOYEE) is None


class TestSummarise:
    def test_no_categories_no_summary(self, policy):
        service = PurposeService(ScriptedRegistry(), policy)
        assert service.summarise(make_claim(make_receipt(category=None))) is None

    def test_business_trip_names_the_most_visited_city(self, policy):
        assert PurposeService(ScriptedRegistry(), policy).summarise(trip_claim()) == TRIP_SUMMARY

    @pytest.mark.parametrize(
        ("categories", "period", "expected"),
        [
            (["meals"], ("2026-10-05", "2026-10-05"), "Business expenses (5 Oct 2026): meals."),
            (["meals", "medical", "meals"], ("2026-10-01", "2026-10-03"),
             "Business expenses (1-3 Oct 2026): meals and medical reimbursement."),
            (["broadband", "medical", "meals"], ("2026-09-28", "2026-10-03"),
             "Business expenses (28 Sep - 3 Oct 2026): broadband reimbursement, medical reimbursement and meals."),
            (["meals"], (None, None), "Business expenses: meals."),
        ],
        ids=["single-day", "same-month-deduplicated", "across-months", "no-dates"],
    )
    def test_everyday_expenses(self, policy, categories, period, expected):
        claim = make_claim(*(make_receipt(category=c, location="Pune") for c in categories),
                           period_start=period[0], period_end=period[1])
        assert PurposeService(ScriptedRegistry(), policy).summarise(claim) == expected

    def test_travel_without_cities_is_described_as_business_expenses(self, policy):
        claim = make_claim(make_receipt(category="airfare", location=None))
        assert PurposeService(ScriptedRegistry(), policy).summarise(claim) == "Business expenses: airfare."

    def test_receipts_not_read_yet_are_ignored(self, policy):
        claim = make_claim(make_receipt(category="meals"), make_receipt(category="lodging", stage=ReceiptStage.READING))
        assert PurposeService(ScriptedRegistry(), policy).summarise(claim) == "Business expenses: meals."


@pytest.mark.parametrize(("key", "label"), [("lodging", "Hotel & Lodging"), ("pet_care", "pet care"), (None, "other")])
def test_label(policy, key, label):
    assert PurposeService(ScriptedRegistry(), policy)._label(key) == label


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Trip for Aarav to Pune", True),
        ("SHARMA family visit", True),
        ("Client visit to Pune", False),
    ],
)
def test_mentions_person(text, expected):
    assert _mentions_person(text, EMPLOYEE) is expected


def test_very_short_name_parts_are_ignored():
    short = EMPLOYEE.model_copy(update={"name": "Al Bo"})
    assert _mentions_person("Albany conference, Bonn hotel", short) is False
