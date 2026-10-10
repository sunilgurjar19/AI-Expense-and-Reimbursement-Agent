"""AgentService: claim creation, uploads, the background pipeline, answers, chat and purpose inference.

The real container is used (mock LLM provider, zero stage delay, temporary storage); background tasks are
awaited deterministically with ``drain``.
"""

import hashlib
import json

import pytest

from app.container import Container
from app.core.events import EventBus
from app.models.domain import ChatMessage, ClaimStatus, Question, ReceiptStage, ReceiptStatus
from app.services.agent_service import ClaimLockedError, UploadError
from app.services.claim_service import AnswerError
from app.services.document_reader import DocumentContent
from app.services.llm import LLMError, LLMResult
from tests.helpers import (
    EMPLOYEE_ID,
    ScriptedRegistry,
    dmy,
    drain,
    make_receipt,
    make_settings,
    photo_bytes,
    recent_weekday,
    sample_pdf,
    upload,
)

TRIP_FILES = ["indigo_flight.pdf", "taj_hotel_invoice.pdf", "uber_ride.pdf", "uber_ride_copy.pdf", "client_dinner.pdf"]


@pytest.fixture
def agent(container):
    return container.agent


@pytest.fixture
def employee(container):
    return container.users.get(EMPLOYEE_ID)


@pytest.fixture
def events(container):
    """Every event published to the employee while the test runs."""
    queue = container.bus.subscribe(EMPLOYEE_ID)
    received = []

    def collect():
        while not queue.empty():
            received.append(queue.get_nowait())
        return received

    return collect


def by_file(claim):
    return {r.file_name: r for r in claim.receipts}


def codes(receipt):
    return {f.code for f in receipt.flags}


def question(claim, kind):
    return next(q for q in claim.questions if q.kind == kind)


def notifications(container, user_id=EMPLOYEE_ID):
    return container.notifications.list(user_id)


def add_completed(container, claim, **receipt_fields):
    """Attach an already-processed receipt (no file needed) and recompute the claim."""
    receipt = make_receipt(claim_id=claim.id, **receipt_fields)
    claim.receipts.append(receipt)
    container.agent.save(claim)
    return receipt


async def processed_trip(agent, employee):
    claim = agent.create_claim(employee, None, None)
    agent.add_receipts(claim, [upload(name) for name in TRIP_FILES])
    await drain(agent)
    return claim


# ----------------------------------------------------------------- claims


class TestCreateClaim:
    def test_a_new_claim_greets_the_employee_and_is_persisted(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)

        assert (claim.title, claim.title_is_auto, claim.status, claim.currency) == (
            "New expense claim", True, ClaimStatus.DRAFT, "INR")
        assert [(e.status, e.label, e.actor) for e in claim.timeline] == [("draft", "Claim created", "Aarav Sharma")]
        assert claim.messages[0].role == "agent" and claim.messages[0].text.startswith("Hi Aarav! 👋 I'm Rika.")
        stored = json.loads(container.settings.resolve_path(container.settings.storage.database_file).read_text())
        assert claim.id in stored["claims"]

    def test_title_and_purpose_can_be_given_up_front(self, agent, employee):
        claim = agent.create_claim(employee, "Q3 offsite", "Team offsite in Goa")
        assert (claim.title, claim.title_is_auto) == ("Q3 offsite", False)
        assert (claim.purpose, claim.purpose_source) == ("Team offsite in Goa", "user")

    def test_deleting_removes_the_claim_and_its_files(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        folder = agent.claim_dir(claim)
        folder.mkdir(parents=True)
        (folder / "x.pdf").write_bytes(b"%PDF")

        agent.delete_claim(claim)

        assert container.claims.get(claim.id) is None and not folder.exists()

    def test_submitted_claims_cannot_be_deleted(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        claim.status = ClaimStatus.SUBMITTED
        with pytest.raises(ClaimLockedError):
            agent.delete_claim(claim)


# ----------------------------------------------------------------- uploads


class TestUploads:
    @pytest.mark.parametrize(
        ("file", "message"),
        [
            (("notes.txt", b"hello", "text/plain"), "notes.txt: unsupported file type (.txt)"),
            (("README", b"hello", None), "README: unsupported file type (none)"),
            (("empty.pdf", b"", "application/pdf"), "empty.pdf: file is empty"),
            (("huge.png", b"0" * (1024 * 1024 + 1), "image/png"), "huge.png: larger than 1 MB"),
        ],
        ids=["extension", "no-extension", "empty", "too-large"],
    )
    async def test_invalid_files_are_rejected(self, tmp_path, file, message):
        container = Container(make_settings(tmp_path, storage={"max_upload_mb": 1}))
        container.bus = EventBus()
        agent = container.agent
        claim = agent.create_claim(container.users.get(EMPLOYEE_ID), None, None)

        with pytest.raises(UploadError, match=message.replace("(", r"\(").replace(")", r"\)")):
            agent.add_receipts(claim, [file])
        assert claim.receipts == [] and agent._tasks == set()

    async def test_uploads_to_a_submitted_claim_are_refused(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        claim.status = ClaimStatus.SUBMITTED
        with pytest.raises(ClaimLockedError, match="can no longer be changed"):
            agent.add_receipts(claim, [upload("uber_ride.pdf")])

    async def test_files_are_stored_and_processed_in_the_background(self, container, agent, employee, events):
        claim = agent.create_claim(employee, None, None)
        pdf, photo = sample_pdf("starbucks_coffee.pdf"), photo_bytes()

        receipts = agent.add_receipts(claim, [("starbucks.pdf", pdf, "application/pdf"), ("chai.png", photo, None)])

        assert [(r.file_name, r.mime_type, r.size_bytes, r.stage) for r in receipts] == [
            ("starbucks.pdf", "application/pdf", len(pdf), ReceiptStage.UPLOADED),
            ("chai.png", "image/png", len(photo), ReceiptStage.UPLOADED),  # guessed from the extension
        ]
        assert receipts[0].sha256 == hashlib.sha256(pdf).hexdigest()
        stored = agent.receipt_path(claim, receipts[1])
        assert stored.parent == container.settings.resolve_path(container.settings.storage.upload_dir) / EMPLOYEE_ID / claim.id
        assert stored.read_bytes() == photo and stored.suffix == ".png"
        assert claim.messages[-1].text.startswith("Got 2 files! 📥 Reading them now")
        assert claim.status == ClaimStatus.PROCESSING and len(agent._tasks) == 1

        await drain(agent)

        assert [r.stage for r in claim.receipts] == [ReceiptStage.COMPLETED, ReceiptStage.COMPLETED]
        assert all(r.progress == 100 for r in claim.receipts)
        assert any(e["type"] == "claim.updated" for e in events())

    async def test_a_single_file_is_acknowledged_in_the_singular(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        assert claim.messages[-1].text.startswith("Got 1 file! 📥 Reading it now")
        await drain(agent)


# ---------------------------------------------------------------- pipeline


class TestPipeline:
    async def test_a_business_trip_is_read_checked_and_summarised(self, container, agent, employee):
        claim = await processed_trip(agent, employee)
        receipts = by_file(claim)

        assert all(r.stage == ReceiptStage.COMPLETED and r.extraction_source == "mock" for r in claim.receipts)
        assert {name: r.data.category for name, r in receipts.items()} == {
            "indigo_flight.pdf": "airfare",
            "taj_hotel_invoice.pdf": "lodging",
            "uber_ride.pdf": "local_conveyance",
            "uber_ride_copy.pdf": "local_conveyance",
            "client_dinner.pdf": "meals",
        }
        hotel, dinner = receipts["taj_hotel_invoice.pdf"], receipts["client_dinner.pdf"]
        original, copy = receipts["uber_ride.pdf"], receipts["uber_ride_copy.pdf"]
        assert "OVER_LIMIT" in codes(hotel) and hotel.reimbursable_amount == 9000.0
        assert "NON_REIMBURSABLE_ITEMS" in codes(dinner) and dinner.reimbursable_amount == 1068.0  # beer deducted
        assert (copy.duplicate_of, copy.duplicate_note, original.duplicate_of) == (original.id, "in this claim", None)
        assert (claim.total_claimed, claim.total_reimbursable) == (27306.1, 18054.1)

        assert claim.status == ClaimStatus.NEEDS_ATTENTION
        assert {q.kind for q in claim.questions} == {"confirm_amount", "justification", "duplicate"}
        assert claim.purpose_source == "agent" and claim.purpose.startswith("Business trip to Bengaluru, ")
        assert claim.purpose.endswith(" - airfare, hotel & lodging, local conveyance & toll tax and meals.")
        assert claim.title.startswith("Bengaluru trip · ")

        summary = claim.messages[-1]
        assert summary.meta == {"kind": "summary"}
        assert "🏨 Taj MG Road Bengaluru - INR 17,472.00" in summary.text
        assert "Claim total so far: **INR 27,306.10** (reimbursable INR 18,054.10)." in summary.text
        assert "📝 I've added the remarks" in summary.text and "I just need 3 quick answers from you 👇" in summary.text
        (note,) = notifications(container)
        assert (note.title, note.level) == ("Receipts processed", "warning")
        assert note.message == f"5 of 5 receipt(s) read for “{claim.title}” · 3 question(s) waiting"

    async def test_answering_every_question_makes_the_claim_ready(self, container, agent, employee):
        claim = await processed_trip(agent, employee)

        agent.answer_question(claim, question(claim, "duplicate").id, "exclude")
        assert claim.messages[-2].text == "Remove duplicate" and claim.messages[-1].text == "Got it 👍 2 more to go."
        agent.answer_question(claim, question(claim, "justification").id, "Conference hotel rate")
        assert claim.messages[-1].text == "Got it 👍 Just one more."
        agent.answer_question(claim, question(claim, "confirm_amount").id, 6331.5)

        assert claim.status == ClaimStatus.READY and claim.readiness == 100 and claim.questions == []
        assert claim.messages[-2].text == "6,331.50"
        assert claim.messages[-1].text == "Perfect, that's everything! 🎉 Your claim for **INR 17,226.80** is ready to submit."
        assert claim.messages[-2].meta["question_id"]
        assert notifications(container)[0].title == "Ready to submit ✨"

    async def test_a_clean_receipt_with_given_remarks_is_ready_straight_away(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Coffee with the Acme team")
        agent.add_receipts(claim, [upload("starbucks_coffee.pdf")])
        await drain(agent)

        receipt = claim.receipts[0]
        assert (receipt.data.vendor, receipt.data.total_amount, receipt.data.category) == ("Starbucks Coffee", 490.0, "meals")
        assert receipt.purpose_inherited and receipt.status == ReceiptStatus.COMPLETE
        assert claim.status == ClaimStatus.READY and claim.purpose_source == "user"
        assert "your claim is **ready to submit** ✅" in claim.messages[-1].text
        assert [(n.title, n.level) for n in notifications(container)] == [
            ("Ready to submit ✨", "success"), ("Receipts processed", "success")]

    async def test_a_handwritten_marathi_memo_is_verified_and_translated(self, container, agent, employee,
                                                                       monkeypatch):
        bill_date = recent_weekday(5)
        reading = {
            "is_receipt": True,
            "language": "Marathi",
            "fields": {"vendor": "Manish Service Center", "vendor_local": "मनिष सर्विस सेंटर",
                       "date_as_printed": dmy(bill_date), "total_amount": 500, "currency": "INR",
                       "invoice_number": "0 14821", "address_as_printed": "महापे, नवी मुंबई", "description": "डीझेल"},
            "confidence": {"vendor": 0.9, "date": 0.9, "total_amount": 0.9},
            "line_items": [{"description": "डीझेल", "quantity": 5, "unit_price": 100, "amount": 500}],
            "notes": "Handwritten cash memo",
        }
        scripted = ScriptedRegistry({
            "extract_receipt": reading,
            "verify_receipt": reading,
            "translate_fields": {"item_0": "Diesel", "description": "Diesel", "address": "Mahape, Navi Mumbai"},
            "infer_purpose": {"purpose": "Fuel for the site visit to Mahape."},
        })
        monkeypatch.setattr(container.llm, "generate", scripted.generate)
        claim = agent.create_claim(employee, None, None)

        agent.add_receipts(claim, [("memo.jpg", photo_bytes(), "image/png")])
        await drain(agent)

        receipt = claim.receipts[0]
        assert scripted.tasks() == ["extract_receipt", "verify_receipt", "translate_fields", "infer_purpose"]
        assert scripted.requests[0].context["zoom"] is True and len(scripted.requests[0].images) == 1
        assert (receipt.data.vendor, receipt.data.vendor_local, receipt.data.location) == (
            "Manish Service Center", "मनिष सर्विस सेंटर", "Mahape, Navi Mumbai")
        assert [i.description for i in receipt.data.line_items] == ["Diesel"] and receipt.data.description == "Diesel"
        assert (receipt.data.date, receipt.data.invoice_number, receipt.data.category) == (bill_date, "014821", "fuel_car")
        assert receipt.extraction_source == "fake"
        assert receipt.extraction_notes == "Handwritten cash memo Double-checked by a second reading."
        assert (claim.purpose, claim.status) == ("Fuel for the site visit to Mahape.", ClaimStatus.READY)

    async def test_every_pipeline_stage_is_broadcast_for_the_live_view(self, tmp_path):
        container = Container(make_settings(tmp_path, pipeline={"stage_delay_ms": 1}))
        container.bus = EventBus()
        queue = container.bus.subscribe(EMPLOYEE_ID)
        agent = container.agent
        claim = agent.create_claim(container.users.get(EMPLOYEE_ID), None, "Airport transfer")

        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        steps, kinds = [], set()
        while not queue.empty():
            event = queue.get_nowait()
            kinds.add(event["type"])
            if event["type"] != "claim.updated":
                continue
            receipt = event["data"]["receipts"][0]
            if not steps or steps[-1] != (receipt["stage"], receipt["progress"]):
                steps.append((receipt["stage"], receipt["progress"]))
        assert steps == [("uploaded", 0), ("reading", 12), ("extracting", 30), ("verifying", 55),
                         ("categorising", 72), ("validating", 85), ("duplicate_check", 95), ("completed", 100)]
        assert kinds == {"claim.updated", "notification"}  # the "Receipts processed" toast travels the same way

    async def test_a_photo_read_by_the_offline_engine_is_flagged_unreadable(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        agent.add_receipts(claim, [("chai_point_photo.png", photo_bytes(), "image/png")])
        await drain(agent)

        receipt = claim.receipts[0]
        assert receipt.read_warning.startswith("The offline rules engine is active")
        assert "UNREADABLE" in codes(receipt)
        assert receipt.data.category == "meals"  # inferred from the file name
        assert receipt.missing_fields == ["vendor", "date", "total_amount", "currency"]
        assert "chai_point_photo.png - amount unknown" in claim.messages[-1].text
        assert "I couldn't read the text on 1 photo/scan(s)" in claim.messages[-1].text

    @pytest.mark.parametrize(
        ("error", "stored"),
        [
            (LLMError("ollama: connection refused"), "ollama: connection refused"),
            (OSError("cannot open file"), "cannot open file"),
            (ValueError("x" * 400), "x" * 300),
            (RuntimeError("secret internals"), "Unexpected error: RuntimeError"),
        ],
        ids=["llm", "os", "value-truncated", "unexpected"],
    )
    async def test_a_failing_receipt_is_marked_failed_without_breaking_the_batch(self, container, agent, employee,
                                                                                 monkeypatch, error, stored):
        def fail(_path, _mime):
            raise error

        claim = agent.create_claim(employee, None, None)
        monkeypatch.setattr(agent._reader, "read", fail)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        receipt = claim.receipts[0]
        assert (receipt.stage, receipt.status, receipt.error, receipt.progress) == (
            ReceiptStage.FAILED, ReceiptStatus.FAILED, stored, 100)
        assert claim.status == ClaimStatus.NEEDS_ATTENTION
        assert "I couldn't read 1 file(s)" in claim.messages[-1].text
        note = notifications(container)[0]
        assert (note.level, note.message.split(" · ")[0]) == ("warning", "0 of 1 receipt(s) read for “New expense claim”")

    async def test_all_providers_failing_marks_the_receipt_failed(self, container, agent, employee, monkeypatch):
        async def offline(_request):
            raise LLMError("ollama: down; mock: down")

        monkeypatch.setattr(container.llm, "generate", offline)
        claim = agent.create_claim(employee, None, None)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)
        assert claim.receipts[0].error == "ollama: down; mock: down"

    async def test_a_receipt_removed_mid_pipeline_is_skipped_quietly(self, agent, employee, monkeypatch):
        claim = agent.create_claim(employee, None, None)

        def remove_then_read(_path, _mime):
            claim.receipts.clear()  # the employee deleted it while it was being read
            return DocumentContent(kind="pdf", text="Uber India\nTotal Rs 100")

        monkeypatch.setattr(agent._reader, "read", remove_then_read)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        assert claim.receipts == []
        assert claim.messages[-1].meta == {"kind": "summary"}

    async def test_a_receipt_that_fails_after_being_removed_is_ignored(self, agent, employee, monkeypatch):
        claim = agent.create_claim(employee, None, None)

        def remove_then_fail(_path, _mime):
            claim.receipts.clear()
            raise OSError("file vanished")

        monkeypatch.setattr(agent._reader, "read", remove_then_fail)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        assert claim.receipts == [] and "couldn't read" not in claim.messages[-1].text

    async def test_a_claim_deleted_mid_pipeline_is_not_resurrected(self, container, agent, employee, monkeypatch):
        claim = agent.create_claim(employee, None, None)

        def delete_then_read(_path, _mime):
            container.claims.delete(claim.id)
            return DocumentContent(kind="pdf", text="Uber India\nTotal Rs 100")

        monkeypatch.setattr(agent._reader, "read", delete_then_read)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        assert container.claims.get(claim.id) is None
        assert notifications(container) == []

    async def test_a_claim_submitted_mid_pipeline_is_left_alone(self, agent, employee, monkeypatch):
        claim = agent.create_claim(employee, None, None)

        def lock_then_read(_path, _mime):
            claim.status = ClaimStatus.SUBMITTED
            return DocumentContent(kind="pdf", text="Uber India\nTotal Rs 100")

        monkeypatch.setattr(agent._reader, "read", lock_then_read)
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)

        assert claim.receipts[0].stage == ReceiptStage.READING and claim.status == ClaimStatus.SUBMITTED

    async def test_retry_reprocesses_a_failed_receipt(self, agent, employee, monkeypatch):
        claim = agent.create_claim(employee, None, "Airport transfer")

        def broken(_path, _mime):
            raise OSError("temporarily unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(agent._reader, "read", broken)
            agent.add_receipts(claim, [upload("uber_ride.pdf")])
            await drain(agent)
        receipt = claim.receipts[0]
        assert receipt.stage == ReceiptStage.FAILED

        agent.retry_receipt(claim, receipt)
        assert (receipt.stage, receipt.progress, receipt.error) == (ReceiptStage.UPLOADED, 0, None)
        await drain(agent)
        assert receipt.stage == ReceiptStage.COMPLETED and claim.status == ClaimStatus.READY

    async def test_retry_is_refused_on_submitted_claims(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        claim.status = ClaimStatus.SUBMITTED
        with pytest.raises(ClaimLockedError):
            agent.retry_receipt(claim, make_receipt(claim_id=claim.id))

    async def test_interrupted_receipts_are_resumed_after_a_restart(self, container, agent, employee):
        def stuck_claim(title, status):
            claim = agent.create_claim(employee, title, "Trip")
            content = sample_pdf("uber_ride.pdf")
            receipt = make_receipt(claim_id=claim.id, stage=ReceiptStage.EXTRACTING, progress=30, file_name="uber.pdf",
                                   sha256=hashlib.sha256(content).hexdigest() + title)
            path = agent.receipt_path(claim, receipt)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            claim.receipts.append(receipt)
            claim.status = status
            container.claims.save(claim)
            return claim, receipt

        (_, editable), (_, locked) = stuck_claim("Open", ClaimStatus.PROCESSING), stuck_claim("Locked", ClaimStatus.SUBMITTED)

        agent.resume_interrupted()
        assert len(agent._tasks) == 1
        await drain(agent)

        assert editable.stage == ReceiptStage.COMPLETED and editable.data.vendor == "Uber India"
        assert locked.stage == ReceiptStage.EXTRACTING


# ----------------------------------------------------------------- answers


class TestAnswers:
    def test_unknown_question(self, agent, employee):
        claim = agent.create_claim(employee, None, None)
        with pytest.raises(AnswerError, match="already answered"):
            agent.answer_question(claim, "q-unknown", "x")

    def test_locked_claims_take_no_answers(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        claim.status = ClaimStatus.SUBMITTED
        with pytest.raises(ClaimLockedError):
            agent.answer_question(claim, claim.questions[0].id, "Client visit")

    def test_invalid_answers_are_rejected_without_changes(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Trip")
        add_completed(container, claim, total_amount=None)
        messages_before = len(claim.messages)
        with pytest.raises(AnswerError, match="valid amount"):
            agent.answer_question(claim, question(claim, "total_amount").id, "lots")
        assert len(claim.messages) == messages_before

    def test_a_blank_answer_to_the_purpose_question_is_rejected(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        with pytest.raises(AnswerError):
            agent.answer_question(claim, question(claim, "purpose").id, "   ")

    @pytest.mark.parametrize(
        ("status", "question_count", "expected"),
        [
            (ClaimStatus.READY, 0, "Perfect, that's everything! 🎉 Your claim for **INR 450.00** is ready to submit."),
            (ClaimStatus.NEEDS_ATTENTION, 3, "Got it 👍 3 more to go."),
            (ClaimStatus.NEEDS_ATTENTION, 1, "Got it 👍 Just one more."),
            (ClaimStatus.PROCESSING, 0, "Got it 👍 I'm still reading the remaining receipts."),
            (ClaimStatus.NEEDS_ATTENTION, 0, "Got it 👍 Please review the highlighted items before submitting."),
        ],
    )
    def test_next_step_message(self, agent, employee, status, question_count, expected):
        claim = agent.create_claim(employee, None, None)
        claim.status, claim.total_reimbursable = status, 450.0
        claim.questions = [Question(key=f"k{n}", kind="vendor", prompt="?") for n in range(question_count)]
        assert agent._next_step_message(claim) == expected


# -------------------------------------------------------------------- chat


class TestChat:
    async def test_offline_agent_answers_questions_about_the_claim(self, container, agent, employee):
        claim = agent.create_claim(employee, "Pune trip", "Client visit")
        add_completed(container, claim, total_amount=1200.0)

        await agent.chat(claim, employee, "What's my total?")

        user, reply = claim.messages[-2:]
        assert (user.role, user.text) == ("user", "What's my total?")
        assert reply.role == "agent" and reply.meta == {"provider": "mock", "applied": 0}
        assert reply.text.startswith("Your claim **Pune trip** has 1 expense(s) totalling INR 1,200.00")

    async def test_a_free_text_reply_answers_the_pending_question(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        assert [q.kind for q in claim.questions] == ["purpose"]

        await agent.chat(claim, employee, "Client visit to Pune")

        assert (claim.purpose, claim.purpose_source, claim.status) == ("Client visit to Pune", "user", ClaimStatus.READY)
        assert claim.messages[-1].meta["applied"] == 1
        assert notifications(container)[0].title == "Ready to submit ✨"

    async def test_structured_actions_are_validated_and_applied(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        receipt = add_completed(container, claim, vendor=None)
        vendor_question = question(claim, "vendor")
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "Updated!",
            "answers": [{"question_id": "q-unknown", "answer": "x"}, {"question_id": vendor_question.id, "answer": " "}],
            "updates": [
                {"receipt_id": receipt.id, "field": "vendor", "value": "Blue Tokai"},
                {"receipt_id": receipt.id, "field": "total_amount", "value": "-1"},
                {"receipt_id": "rcpt-missing", "field": "vendor", "value": "Ghost"},
            ],
            "claim_purpose": "Sales offsite",
        }})

        await agent.chat(claim, employee, "The merchant was Blue Tokai, for the sales offsite")

        assert (receipt.data.vendor, receipt.data.total_amount) == ("Blue Tokai", 450.0)
        assert (claim.purpose, claim.purpose_source) == ("Sales offsite", "user")
        assert claim.messages[-1].text == "Updated!" and claim.messages[-1].meta == {"provider": "fake", "applied": 2}
        assert claim.status == ClaimStatus.READY
        (request,) = agent._registry.requests
        assert request.task == "chat" and "You are Rika" in request.system and "Acme Corp" in request.system
        assert request.context["pending_questions"][0]["id"] == vendor_question.id
        assert "Employee: Aarav Sharma" in request.prompt and "User message: The merchant was" in request.prompt

    @staticmethod
    def over_limit_hotel(container, agent, employee):
        claim = agent.create_claim(employee, None, "Client workshop")
        receipt = add_completed(container, claim, vendor="Taj MG Road Bengaluru", category="lodging", total_amount=17472.0)
        return claim, receipt, question(claim, "justification")

    async def test_a_question_does_not_answer_pending_questions(self, container, agent, employee):
        # Seen live with gemma3:4b: "What's my total?" came back with the justification "answered" by a
        # paraphrase of the question itself.
        claim, receipt, justification = self.over_limit_hotel(container, agent, employee)
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "Your total claimed so far is INR 17,472.00.",
            "answers": [{"question_id": justification.id, "answer": "Please add a short justification for the "
                         "Taj MG Road Bengaluru receipt exceeding the policy limit."}],
        }})

        await agent.chat(claim, employee, "What's my total?")

        assert receipt.justification is None and [q.kind for q in claim.questions] == ["justification"]
        assert claim.messages[-1].meta["applied"] == 0

    async def test_the_employees_words_answer_when_the_model_copies_the_question(self, container, agent, employee):
        # Seen live with gemma3:4b: it targeted the right question but "answered" with the question's wording.
        claim, receipt, justification = self.over_limit_hotel(container, agent, employee)
        message = "The Taj was the client's venue for the workshop and the company hotel was sold out."
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "Thanks, noted.",
            "answers": [{"question_id": justification.id, "answer": "The Taj MG Road Bengaluru receipt is above the "
                         "policy limit. Please add a justification for your approver."}],
        }})

        await agent.chat(claim, employee, message)

        assert receipt.justification == message and claim.status == ClaimStatus.READY
        assert claim.messages[-1].text == "Thanks, noted." and claim.messages[-1].meta["applied"] == 1

    async def test_no_guessing_when_the_model_targets_several_questions(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim, vendor="Taj MG Road Bengaluru", category="lodging", total_amount=17472.0)
        add_completed(container, claim, vendor="Toit", category="meals", total_amount=900.0)
        container.claim_service.set_purpose(claim, "", source="user")
        container.agent.save(claim)
        open_before = [q.kind for q in claim.questions]
        targets = [q for q in claim.questions if q.kind in ("justification", "purpose")]
        assert len(targets) == 2
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "ok", "answers": [{"question_id": q.id, "answer": q.prompt} for q in targets],
        }})

        await agent.chat(claim, employee, "The Taj was the client's venue and the company hotel was sold out.")

        assert claim.messages[-1].meta["applied"] == 0 and [q.kind for q in claim.questions] == open_before

    @pytest.mark.parametrize("reply", ["Okay, I've added a note about the venue.", "I've marked this as a note.",
                                       "Updating the hotel receipt now.", "I made a note of that."])
    async def test_a_reply_claiming_an_unrecorded_change_is_corrected(self, container, agent, employee, reply):
        claim, receipt, _ = self.over_limit_hotel(container, agent, employee)
        agent._registry = ScriptedRegistry({"chat": {"reply": reply}})

        await agent.chat(claim, employee, "Thanks!")

        assert receipt.justification is None
        assert claim.messages[-1].text == (
            f"{reply}\n\n_(Nothing was changed: answer with the question cards, or edit the receipt.)_")

    @pytest.mark.parametrize("reply", ["Yes, you're all set! 🎉", "Your total is INR 17,472.00.", "Savings add up!"])
    async def test_ordinary_replies_are_left_alone(self, container, agent, employee, reply):
        claim, _, _ = self.over_limit_hotel(container, agent, employee)
        agent._registry = ScriptedRegistry({"chat": {"reply": reply}})
        await agent.chat(claim, employee, "Is this ready to submit?")
        assert claim.messages[-1].text == reply

    async def test_a_justification_stated_in_chat_is_applied(self, container, agent, employee):
        claim, receipt, justification = self.over_limit_hotel(container, agent, employee)
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "Thanks, added.",
            "answers": [{"question_id": justification.id, "answer": "Client's venue; the company hotel was sold out"}],
        }})

        await agent.chat(claim, employee, "The Taj was the client's venue and the company hotel was sold out.")

        assert receipt.justification == "Client's venue; the company hotel was sold out"
        assert claim.status == ClaimStatus.READY and claim.messages[-1].meta["applied"] == 1

    async def test_a_passing_remark_does_not_replace_the_agent_remarks(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        container.claim_service.set_purpose(claim, "Business trip to Pune", source="agent")
        message = "The Taj was the client's venue for the workshop."
        agent._registry = ScriptedRegistry({"chat": {"reply": "Noted", "claim_purpose": message}})

        await agent.chat(claim, employee, message)

        assert (claim.purpose, claim.purpose_source) == ("Business trip to Pune", "agent")
        assert claim.messages[-1].meta["applied"] == 0

    async def test_remarks_change_when_the_employee_asks(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        container.claim_service.set_purpose(claim, "Business trip to Pune", source="agent")
        agent._registry = ScriptedRegistry({"chat": {"reply": "Done", "claim_purpose": "Client workshop in Pune"}})

        await agent.chat(claim, employee, "Please change the remarks to: client workshop in Pune")

        assert (claim.purpose, claim.purpose_source) == ("Client workshop in Pune", "user")

    async def test_the_model_only_sees_live_totals(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Trip")
        add_completed(container, claim)
        claim.messages.append(ChatMessage(role="agent", text="Claim total so far: **INR 99,999.00**",
                                          meta={"kind": "summary"}))
        agent._registry = ScriptedRegistry({"chat": {"reply": "INR 450.00"}})

        await agent.chat(claim, employee, "What's my total?")

        (request,) = agent._registry.requests
        assert "99,999" not in request.prompt and "99,999" not in request.context["transcript"]
        assert '"total_claimed": 450.0' in request.prompt and "out of date" in request.system

    async def test_stated_but_invalid_values_are_still_validated(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Trip")
        receipt = add_completed(container, claim, currency=None)
        currency_question = question(claim, "currency")
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "Noted",
            "answers": [{"question_id": currency_question.id, "answer": "XYZ"}],
            "updates": [{"receipt_id": receipt.id, "field": "currency", "value": "XYZ"}],
        }})

        await agent.chat(claim, employee, "It was paid in XYZ")

        assert receipt.data.currency is None and claim.messages[-1].meta["applied"] == 0

    async def test_model_cannot_overwrite_remarks_the_employee_wrote(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Written by me")
        add_completed(container, claim)
        agent._registry = ScriptedRegistry({"chat": {"reply": "Noted", "claim_purpose": "Model's idea"}})
        await agent.chat(claim, employee, "hello")
        assert claim.purpose == "Written by me" and claim.messages[-1].meta["applied"] == 0

    async def test_provider_failure_gets_an_apology(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        agent._registry = ScriptedRegistry({"chat": LLMError("everything is down")})
        await agent.chat(claim, employee, "hello")
        assert claim.messages[-1].text.startswith("Sorry, I'm having trouble thinking right now")
        assert claim.messages[-1].meta == {"provider": None, "applied": 0}

    async def test_an_empty_model_reply_falls_back_to_the_next_step(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._registry = ScriptedRegistry({"chat": "not even json"})
        await agent.chat(claim, employee, "hello")
        assert claim.messages[-1].text == "Got it 👍 Just one more."

    async def test_submitted_claims_can_be_discussed_but_not_changed(self, container, agent, employee):
        claim = agent.create_claim(employee, None, "Trip")
        receipt = add_completed(container, claim)
        claim.status = ClaimStatus.SUBMITTED
        agent._registry = ScriptedRegistry({"chat": {
            "reply": "It's with your manager.",
            "updates": [{"receipt_id": receipt.id, "field": "vendor", "value": "Changed"}],
        }})
        await agent.chat(claim, employee, "Where is my claim?")
        assert receipt.data.vendor == "Uber India" and claim.messages[-1].text == "It's with your manager."

    @pytest.mark.parametrize("payload", [{"reply": "ok", "answers": ["yes"]}, {"reply": "ok", "updates": "vendor=Taj"}],
                             ids=["string-answer", "string-updates"])
    async def test_malformed_actions_from_the_model_are_ignored(self, container, agent, employee, payload):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._registry = ScriptedRegistry({"chat": payload})
        await agent.chat(claim, employee, "hello")
        assert claim.messages[-1].text == "ok"

    async def test_a_claim_deleted_while_the_agent_is_replying_stays_deleted(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)

        async def delete_while_thinking(_request):
            agent.delete_claim(claim)
            return LLMResult(text='{"reply": "Sure"}', provider="fake", fell_back=False)

        agent._registry = ScriptedRegistry({"chat": delete_while_thinking})
        await agent.chat(claim, employee, "hello")
        assert container.claims.get(claim.id) is None


# ------------------------------------------------------------------ purpose


class FakePurpose:
    def __init__(self, result=None, error=None, during=None):
        self.result, self.error, self.during = result, error, during
        self.calls = 0

    async def infer(self, claim, employee):
        self.calls += 1
        assert claim.purpose_inferring is True  # the UI shows a spinner meanwhile
        if self.during:
            self.during(claim)
        if self.error:
            raise self.error
        return self.result


class TestPurposeInference:
    async def test_the_agent_fills_in_the_remarks(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._purpose = FakePurpose("Airport transfer in Pune.")
        await agent._infer_purpose(claim)
        assert (claim.purpose, claim.purpose_source, claim.purpose_inferring) == ("Airport transfer in Pune.", "agent", False)
        assert claim.status == ClaimStatus.READY

    @pytest.mark.parametrize("situation", ["employee-wrote-it", "claim-submitted"])
    async def test_inference_is_skipped(self, container, agent, employee, situation):
        claim = agent.create_claim(employee, None, "Mine" if situation == "employee-wrote-it" else None)
        if situation == "claim-submitted":
            claim.status = ClaimStatus.SUBMITTED
        agent._purpose = fake = FakePurpose("Agent text")
        await agent._infer_purpose(claim)
        assert fake.calls == 0 and claim.purpose in ("Mine", None)

    async def test_remarks_typed_during_inference_win(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._purpose = FakePurpose("Agent text", during=lambda c: container.claim_service.set_purpose(c, "Typed"))
        await agent._infer_purpose(claim)
        assert (claim.purpose, claim.purpose_source) == ("Typed", "user")

    async def test_nothing_inferred_leaves_the_purpose_empty(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._purpose = FakePurpose(None)
        await agent._infer_purpose(claim)
        assert claim.purpose is None and claim.purpose_inferring is False
        assert [q.kind for q in claim.questions] == ["purpose"]  # now the employee is asked

    async def test_the_spinner_is_cleared_even_if_inference_crashes(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._purpose = FakePurpose(error=RuntimeError("bug"))
        with pytest.raises(RuntimeError):
            await agent._infer_purpose(claim)
        assert claim.purpose_inferring is False

    async def test_nothing_is_posted_for_a_claim_deleted_during_inference(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        agent._purpose = FakePurpose("Agent text", during=lambda c: agent.delete_claim(c))
        agent.add_receipts(claim, [upload("uber_ride.pdf")])
        await drain(agent)
        assert container.claims.get(claim.id) is None
        assert notifications(container) == []  # no "Receipts processed" for a claim that no longer exists

    async def test_a_claim_deleted_during_inference_stays_deleted(self, container, agent, employee):
        claim = agent.create_claim(employee, None, None)
        add_completed(container, claim)
        agent._purpose = FakePurpose("Agent text", during=lambda c: agent.delete_claim(c))
        await agent._infer_purpose(claim)
        assert container.claims.get(claim.id) is None


async def test_save_recomputes_persists_and_broadcasts(container, agent, employee, events):
    claim = agent.create_claim(employee, None, None)
    claim.receipts.append(make_receipt(claim_id=claim.id))
    events()  # discard the creation events

    agent.save(claim)

    assert claim.status == ClaimStatus.NEEDS_ATTENTION
    published = events()
    assert [e["type"] for e in published] == ["claim.updated"] and published[0]["data"]["id"] == claim.id
