"""HTTP API through FastAPI's TestClient: the real app and routes on an isolated container (mock LLM)."""

import csv
import io
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.routes import notifications as notification_routes
from app.core.security import create_access_token
from app.models.domain import ClaimStatus, ReceiptStage
from tests.helpers import EMPLOYEE_ID, make_claim, make_receipt, photo_bytes, recent_weekday, sample_pdf, upload

YEAR = f"{datetime.now():%Y}"
TRIP_FILES = ["indigo_flight.pdf", "taj_hotel_invoice.pdf", "uber_ride.pdf", "uber_ride_copy.pdf", "client_dinner.pdf"]


def ready_claim(api, user: str = "employee", files=("starbucks_coffee.pdf",), purpose="Coffee with the Acme team"):
    claim = api.create_claim(user, purpose=purpose)
    claim = api.process(claim["id"], [upload(name) for name in files], user)
    assert claim["status"] == "ready", claim["questions"]
    return claim


def submitted_claim(api, user: str = "employee", **kwargs):
    claim = ready_claim(api, user, **kwargs)
    response = api.post(f"/api/claims/{claim['id']}/submit", user)
    assert response.status_code == 200, response.text
    return response.json()


def question(claim: dict, kind: str) -> dict:
    return next(q for q in claim["questions"] if q["kind"] == kind)


# ------------------------------------------------------------------- auth


class TestAuth:
    def test_health_needs_no_login(self, api):
        assert api.client.get("/api/health").json() == {"status": "ok"}

    def test_login_returns_a_token_and_the_public_profile(self, api):
        response = api.client.post("/api/auth/login", json={"username": "  Employee ", "password": "employee123"})
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer" and body["access_token"]
        assert body["user"] == {"id": EMPLOYEE_ID, "username": "employee", "name": "Aarav Sharma",
                                "email": "aarav.sharma@acme.example", "role": "employee",
                                "department": "Product Engineering", "employee_code": "EMP-1001",
                                "cost_center": "CC-ENG-401"}

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"username": "employee", "password": "wrong"}, 401),
            ({"username": "nobody", "password": "employee123"}, 401),
            ({"username": "employee", "password": "EMPLOYEE123"}, 401),
            ({"username": "", "password": "x"}, 422),
            ({"username": "employee"}, 422),
        ],
    )
    def test_login_failures(self, api, body, status):
        response = api.client.post("/api/auth/login", json=body)
        assert response.status_code == status
        if status == 401:
            assert response.json() == {"detail": "Invalid username or password"}

    def test_non_ascii_password_is_just_a_wrong_password(self, api):
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post("/api/auth/login", json={"username": "employee", "password": "pässwörd₹"})
        assert response.status_code == 401

    def test_me_accepts_a_bearer_header_or_an_access_token_query_parameter(self, api):
        assert api.get("/api/auth/me").json()["id"] == EMPLOYEE_ID
        by_query = api.client.get("/api/auth/me", params={"access_token": api.token("manager")})
        assert by_query.status_code == 200 and by_query.json()["role"] == "manager"

    @pytest.mark.parametrize(
        ("headers", "detail"),
        [
            ({}, "Not authenticated"),
            ({"Authorization": "Bearer not-a-jwt"}, "Session expired, please sign in again"),
            ({"Authorization": f"Bearer {create_access_token('u-9999')}"}, "Unknown user"),
        ],
        ids=["missing", "invalid", "unknown-user"],
    )
    def test_protected_routes_need_a_valid_token(self, api, headers, detail):
        response = api.client.get("/api/claims", headers=headers)
        assert (response.status_code, response.json()) == (401, {"detail": detail})

    def test_demo_users_are_listed_for_the_login_page(self, api):
        users = api.client.get("/api/auth/demo-users").json()
        assert [(u["username"], u["password"], u["role"]) for u in users] == [
            ("employee", "employee123", "employee"), ("priya", "priya123", "employee"), ("manager", "manager123", "manager")]

    def test_demo_users_can_be_hidden(self, api_factory):
        api = api_factory(auth={"show_demo_users": False})
        assert api.client.get("/api/auth/demo-users").json() == []


# ------------------------------------------------------------------- meta


def test_public_config_describes_policy_and_ui_settings(api):
    assert api.client.get("/api/config").status_code == 401
    config = api.get("/api/config").json()
    assert (config["agent_name"], config["company"], config["currency"], config["llm_provider"]) == (
        "Rika", "Acme Corp", "INR", "mock")
    assert config["pipeline_stages"][0] == "uploaded" and config["pipeline_stages"][-1] == "completed"
    assert config["currencies"] == ["INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY"]
    lodging = next(c for c in config["categories"] if c["key"] == "lodging")
    assert lodging == {"key": "lodging", "label": "Hotel & Lodging", "icon": "🏨", "limit_per_item": 9000.0,
                       "requires": [], "excludes": []}  # keywords are internal
    assert config["policy"]["max_receipt_age_days"] == 90 and "beer" in config["policy"]["blocked_keywords"]


# ----------------------------------------------------------------- claims


class TestClaims:
    def test_create_list_get_update_and_delete(self, api):
        created = api.create_claim(title="Pune visit", purpose="Client workshop")
        assert (created["title"], created["title_is_auto"], created["purpose_source"], created["status"]) == (
            "Pune visit", False, "user", "draft")

        (summary,) = api.get("/api/claims").json()
        assert {k: summary[k] for k in ("id", "title", "status", "receipt_count", "pending_questions", "owner_name")} == {
            "id": created["id"], "title": "Pune visit", "status": "draft", "receipt_count": 0,
            "pending_questions": 0, "owner_name": None}
        assert api.get(f"/api/claims/{created['id']}").json()["id"] == created["id"]

        updated = api.patch(f"/api/claims/{created['id']}", json={"title": "  " + "T" * 200, "purpose": ""}).json()
        assert updated["title"] == "T" * 120 and updated["purpose"] is None
        unchanged = api.patch(f"/api/claims/{created['id']}", json={"title": "   "}).json()
        assert unchanged["title"] == "T" * 120  # blank titles are ignored

        assert api.delete(f"/api/claims/{created['id']}").status_code == 204
        assert api.get(f"/api/claims/{created['id']}").status_code == 404

    @pytest.mark.parametrize("user", ["priya", "manager"])
    def test_claims_are_private_to_their_owner(self, api, user):
        claim = api.create_claim()
        for method, kwargs in [("get", {}), ("patch", {"json": {"title": "Mine now"}}), ("delete", {})]:
            response = getattr(api, method)(f"/api/claims/{claim['id']}", user, **kwargs)
            assert (response.status_code, response.json()) == (404, {"detail": "Claim not found"})
        assert api.get("/api/claims", user).json() == []
        assert api.get(f"/api/claims/{claim['id']}/receipts/x/file", user).status_code == 404

    def test_unknown_claim(self, api):
        assert api.get("/api/claims/clm-missing").status_code == 404


# ------------------------------------------------------- receipts & pipeline


class TestUploadAndProcessing:
    def test_a_business_trip_goes_from_upload_to_payout(self, api):
        claim = api.create_claim()
        response = api.upload(claim["id"], [upload(name) for name in TRIP_FILES])
        assert response.status_code == 202
        assert [(r["file_name"], r["stage"]) for r in response.json()] == [(name, "uploaded") for name in TRIP_FILES]

        api.settle()
        claim = api.claim(claim["id"])
        assert claim["status"] == "needs_attention"
        assert {q["kind"] for q in claim["questions"]} == {"confirm_amount", "justification", "duplicate"}
        assert (claim["total_claimed"], claim["total_reimbursable"]) == (27306.1, 18054.1)
        assert claim["purpose_source"] == "agent" and claim["title"].startswith("Bengaluru trip · ")

        for kind, answer in [("duplicate", "exclude"), ("justification", "Conference rate"), ("confirm_amount", "6331.50")]:
            response = api.post(f"/api/claims/{claim['id']}/questions/{question(claim, kind)['id']}/answer",
                                json={"answer": answer})
            assert response.status_code == 200, response.text
            claim = response.json()
        assert (claim["status"], claim["readiness"], claim["total_reimbursable"]) == ("ready", 100, 17226.8)

        claim = api.post(f"/api/claims/{claim['id']}/submit").json()
        assert claim["status"] == "submitted" and claim["reference_no"] == f"EXP-{YEAR}-00001"

        (queued,) = api.get("/api/approvals", "manager").json()
        assert (queued["id"], queued["owner_name"], queued["receipt_count"]) == (claim["id"], "Aarav Sharma", 4)
        decision = api.post(f"/api/approvals/{claim['id']}", "manager", json={"decision": "approve", "comment": "OK"})
        assert decision.status_code == 200 and decision.json()["status"] in ("approved", "paid")

        api.settle()
        claim = api.claim(claim["id"])
        assert claim["status"] == "paid"
        assert [e["status"] for e in claim["timeline"]] == [
            "draft", "submitted", "manager_review", "approved", "finance_processing", "paid"]
        titles = [n["title"] for n in api.get("/api/notifications").json()]
        assert titles == ["Money on its way 💸", "Claim approved ✅", "Claim submitted 🚀", "Ready to submit ✨",
                          "Receipts processed"]
        assert [n["title"] for n in api.get("/api/notifications", "manager").json()] == ["Approval needed"]

    def test_rejected_uploads_explain_why(self, api):
        claim = api.create_claim()
        response = api.upload(claim["id"], [upload("uber_ride.pdf"), ("notes.txt", b"hi", "text/plain")])
        assert (response.status_code, response.json()) == (400, {"detail": "notes.txt: unsupported file type (.txt)"})
        assert api.claim(claim["id"])["receipts"] == []
        assert api.post(f"/api/claims/{claim['id']}/receipts").status_code == 422  # no files at all

    def test_photos_need_their_details_typed_in(self, api):
        claim = api.create_claim()
        claim = api.process(claim["id"], [("chai_point_photo.png", photo_bytes(), "image/png")])
        receipt = claim["receipts"][0]
        assert receipt["read_warning"].startswith("The offline rules engine is active")
        assert [q["kind"] for q in claim["questions"]] == ["vendor", "date", "total_amount", "currency"]

        bad = api.post(f"/api/claims/{claim['id']}/questions/{question(claim, 'total_amount')['id']}/answer",
                       json={"answer": "a lot"})
        assert (bad.status_code, bad.json()) == (422, {"detail": "Please enter a valid amount"})

        edited = api.patch(f"/api/claims/{claim['id']}/receipts/{receipt['id']}", json={
            "vendor": "Chai Point", "date": recent_weekday(), "total_amount": 270, "currency": "INR"})
        assert edited.status_code == 200
        claim = edited.json()
        assert claim["status"] == "ready" and claim["receipts"][0]["read_warning"] is None
        assert claim["receipts"][0]["confirmed_fields"] == ["vendor", "date", "total_amount", "currency"]


class TestReceiptEndpoints:
    def test_edit_exclude_and_delete_a_receipt(self, api):
        claim = ready_claim(api, files=("starbucks_coffee.pdf", "uber_ride.pdf"))
        coffee, ride = claim["receipts"]
        url = f"/api/claims/{claim['id']}/receipts"

        invalid = api.patch(f"{url}/{coffee['id']}", json={"currency": "XYZ"})
        assert (invalid.status_code, invalid.json()) == (422, {"detail": "Unsupported currency"})
        assert api.patch(f"{url}/rcpt-missing", json={"vendor": "x"}).status_code == 404

        claim = api.patch(f"{url}/{coffee['id']}", json={"excluded": True}).json()
        assert claim["receipts"][0]["status"] == "excluded" and claim["total_claimed"] == 827.3

        stored = api.container.agent.receipt_path(api.container.claims.get(claim["id"]),
                                                  api.container.claims.get(claim["id"]).receipt(ride["id"]))
        assert stored.exists()
        claim = api.delete(f"{url}/{ride['id']}").json()
        assert [r["id"] for r in claim["receipts"]] == [coffee["id"]] and not stored.exists()
        assert api.delete(f"{url}/{ride['id']}").status_code == 404

    def test_retry_runs_the_pipeline_again(self, api):
        claim = ready_claim(api, files=("uber_ride.pdf",))
        receipt_id = claim["receipts"][0]["id"]
        response = api.post(f"/api/claims/{claim['id']}/receipts/{receipt_id}/retry")
        assert response.status_code == 200
        api.settle()
        assert api.claim(claim["id"])["receipts"][0]["stage"] == "completed"
        assert api.post(f"/api/claims/{claim['id']}/receipts/rcpt-missing/retry").status_code == 404

    def test_documents_can_be_viewed_downloaded_and_zipped(self, api):
        claim = ready_claim(api, files=("starbucks_coffee.pdf", "uber_ride.pdf"))
        coffee, ride = claim["receipts"]
        base = f"/api/claims/{claim['id']}"

        inline = api.get(f"{base}/receipts/{coffee['id']}/file")
        assert inline.status_code == 200 and inline.headers["content-type"] == "application/pdf"
        assert inline.headers["content-disposition"].startswith("inline")
        assert inline.content == sample_pdf("starbucks_coffee.pdf")  # byte-for-byte what was uploaded
        download = api.get(f"{base}/receipts/{coffee['id']}/file", params={"download": "true"})
        assert download.headers["content-disposition"] == 'attachment; filename="starbucks_coffee.pdf"'
        assert api.get(f"{base}/receipts/rcpt-missing/file").json() == {"detail": "File not found"}

        api.patch(f"{base}/receipts/{coffee['id']}", json={"excluded": True})
        archive = api.get(f"{base}/attachments.zip")
        assert archive.headers["content-disposition"] == f'attachment; filename="{claim["id"]}-receipts.zip"'
        assert zipfile.ZipFile(io.BytesIO(archive.content)).namelist() == ["01_uber_ride.pdf"]

        api.container.agent.receipt_path(api.container.claims.get(claim["id"]),
                                         api.container.claims.get(claim["id"]).receipt(ride["id"])).unlink()
        assert api.get(f"{base}/receipts/{ride['id']}/file").status_code == 404  # file gone from disk
        assert api.get(f"{base}/attachments.zip").json() == {"detail": "This claim has no documents"}


class TestConversation:
    def test_answering_an_unknown_question(self, api):
        claim = api.create_claim()
        response = api.post(f"/api/claims/{claim['id']}/questions/q-404/answer", json={"answer": "x"})
        assert (response.status_code, response.json()) == (422, {"detail": "This question was already answered"})

    def test_chat_with_the_agent(self, api):
        claim = ready_claim(api)
        claim = api.post(f"/api/claims/{claim['id']}/chat", json={"message": "  what's my total?  "}).json()
        user, agent = claim["messages"][-2:]
        assert (user["role"], user["text"]) == ("user", "what's my total?")
        assert agent["text"].startswith(f"Your claim **{claim['title']}** has 1 expense(s) totalling INR 490.00")

    @pytest.mark.parametrize("message", ["", "x" * 4001])
    def test_chat_message_length_is_validated(self, api, message):
        claim = api.create_claim()
        assert api.post(f"/api/claims/{claim['id']}/chat", json={"message": message}).status_code == 422

    def test_a_blank_purpose_answer_is_a_validation_error(self, api):
        claim = api.create_claim()
        claim = api.process(claim["id"], [upload("uber_ride.pdf")])
        claim = api.patch(f"/api/claims/{claim['id']}", json={"purpose": ""}).json()
        purpose_question = question(claim, "purpose")
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post(f"/api/claims/{claim['id']}/questions/{purpose_question['id']}/answer",
                                   json={"answer": "  "}, headers=api.headers())
        assert response.status_code == 422


# ---------------------------------------------------------------- lifecycle


class TestLifecycle:
    def test_only_ready_claims_can_be_submitted(self, api):
        claim = api.create_claim()
        response = api.post(f"/api/claims/{claim['id']}/submit")
        assert (response.status_code, response.json()) == (409, {"detail": "Only claims that are ready can be submitted"})

    def test_submitted_claims_are_locked(self, api):
        claim = submitted_claim(api)
        base, receipt_id = f"/api/claims/{claim['id']}", claim["receipts"][0]["id"]
        locked = [
            api.patch(base, json={"title": "New"}),
            api.patch(f"{base}/receipts/{receipt_id}", json={"vendor": "New"}),
            api.delete(f"{base}/receipts/{receipt_id}"),
            api.delete(base),
            api.upload(claim["id"], [upload("uber_ride.pdf")]),
            api.post(f"{base}/receipts/{receipt_id}/retry"),
            api.post(f"{base}/questions/q-1/answer", json={"answer": "x"}),
            api.post(f"{base}/submit"),
            api.post(f"{base}/reopen"),
        ]
        assert [r.status_code for r in locked] == [409] * len(locked)
        assert api.claim(claim["id"])["status"] == "submitted"

    def test_returned_claims_can_be_reopened_and_resubmitted(self, api):
        claim = submitted_claim(api)
        returned = api.post(f"/api/approvals/{claim['id']}", "manager", json={"decision": "reject", "comment": "Add a bill"})
        assert returned.json()["status"] == "rejected"
        assert api.get("/api/notifications").json()[0]["title"] == "Claim returned"

        reopened = api.post(f"/api/claims/{claim['id']}/reopen").json()
        assert reopened["status"] == "ready"  # nothing is missing, so it is immediately submittable again
        assert reopened["timeline"][-1]["status"] == "reopened"
        assert api.post(f"/api/claims/{claim['id']}/submit").json()["status"] == "submitted"

    def test_csv_export(self, api):
        claim = ready_claim(api, files=("starbucks_coffee.pdf", "client_dinner.pdf"), purpose="Team dinner")
        response = api.get(f"/api/claims/{claim['id']}/export")
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"] == f'attachment; filename="{claim["id"]}.csv"'
        header, *rows = list(csv.reader(io.StringIO(response.text)))
        assert header == ["Date", "Merchant", "Category", "Currency", "Amount", "Amount (INR)", "Reimbursable (INR)",
                          "Invoice #", "Purpose", "Notes"]
        dinner = next(r for r in rows if r[1] == "Toit Brewpub Indiranagar")
        assert dinner[2:9] == ["meals", "INR", "1848.0", "1848.0", "1068.0", "TB-20931", "Team dinner"]
        assert "non-reimbursable items" in dinner[9]
        assert len(rows) == 2

        submitted = api.post(f"/api/claims/{claim['id']}/submit").json()
        exported = api.get(f"/api/claims/{claim['id']}/export")
        assert exported.headers["content-disposition"] == f'attachment; filename="{submitted["reference_no"]}.csv"'


# ---------------------------------------------------------------- approvals


class TestApprovals:
    def test_only_managers_see_the_queue(self, api):
        claim = submitted_claim(api)
        for url in ("/api/approvals", f"/api/approvals/{claim['id']}"):
            response = api.get(url)
            assert (response.status_code, response.json()) == (403, {"detail": "Manager access required"})
        assert api.post(f"/api/approvals/{claim['id']}", json={"decision": "approve"}).status_code == 403

    def test_queue_shows_the_teams_submitted_claims_only(self, api):
        mine = submitted_claim(api, "priya")
        api.create_claim("employee")  # a draft: not the manager's business yet
        queue = api.get("/api/approvals", "manager").json()
        assert [(c["id"], c["owner_name"], c["status"]) for c in queue] == [(mine["id"], "Priya Nair", "submitted")]
        detail = api.get(f"/api/approvals/{mine['id']}", "manager").json()
        assert detail["reference_no"] == mine["reference_no"]

    def test_draft_and_unknown_claims_are_hidden(self, api):
        draft = api.create_claim()
        for claim_id in (draft["id"], "clm-missing"):
            assert api.get(f"/api/approvals/{claim_id}", "manager").status_code == 404
            assert api.post(f"/api/approvals/{claim_id}", "manager", json={"decision": "approve"}).status_code == 404

    def test_decisions_are_validated(self, api):
        claim = submitted_claim(api)
        url = f"/api/approvals/{claim['id']}"
        assert api.post(url, "manager", json={"decision": "maybe"}).status_code == 422
        assert api.post(url, "manager", json={"decision": "approve", "comment": "x" * 1001}).status_code == 422
        assert api.post(url, "manager", json={"decision": "reject"}).status_code == 200
        second = api.post(url, "manager", json={"decision": "approve"})
        assert (second.status_code, second.json()) == (409, {"detail": "This claim is not awaiting approval"})

    def test_manager_can_open_the_teams_documents(self, api):
        claim = submitted_claim(api)
        receipt_id = claim["receipts"][0]["id"]
        file = api.get(f"/api/approvals/{claim['id']}/receipts/{receipt_id}/file", "manager")
        assert file.status_code == 200 and file.content[:4] == b"%PDF"
        archive = api.get(f"/api/approvals/{claim['id']}/attachments.zip", "manager")
        assert archive.headers["content-disposition"] == f'attachment; filename="{claim["reference_no"]}-receipts.zip"'
        assert zipfile.ZipFile(io.BytesIO(archive.content)).namelist() == ["01_starbucks_coffee.pdf"]


# ------------------------------------------------------- notifications & SSE


def test_notifications_can_be_marked_read(api):
    ready_claim(api)
    first, second = api.get("/api/notifications").json()
    assert not first["read"] and not second["read"]

    assert api.post(f"/api/notifications/{second['id']}/read").status_code == 204
    assert [n["read"] for n in api.get("/api/notifications").json()] == [False, True]
    assert api.post("/api/notifications/read-all").status_code == 204
    assert [n["read"] for n in api.get("/api/notifications").json()] == [True, True]


class FakeRequest:
    """Stands in for starlette's Request: reports a disconnect after ``connected_checks`` polls."""

    def __init__(self, connected_checks: int) -> None:
        self.remaining = connected_checks

    async def is_disconnected(self) -> bool:
        self.remaining -= 1
        return self.remaining < 0


async def test_event_stream_sends_ready_events_and_keepalives_until_the_browser_leaves(container):
    container.settings.notifications.heartbeat_seconds = 0.01  # don't wait 15 s for a keep-alive
    user = container.users.get(EMPLOYEE_ID)
    response = await notification_routes.event_stream(FakeRequest(connected_checks=2), user, container)
    assert response.media_type == "text/event-stream"
    assert (response.headers["cache-control"], response.headers["x-accel-buffering"]) == ("no-cache", "no")

    stream = response.body_iterator
    assert await anext(stream) == "event: ready\ndata: {}\n\n"
    container.bus.publish(EMPLOYEE_ID, "notification", {"title": "Hi", "at": datetime(2026, 10, 5, tzinfo=timezone.utc)})
    assert await anext(stream) == 'event: notification\ndata: {"title": "Hi", "at": "2026-10-05 00:00:00+00:00"}\n\n'
    assert await anext(stream) == ": keep-alive\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert EMPLOYEE_ID not in container.bus._subscribers  # the subscription is cleaned up


# ----------------------------------------------------------------- settings


class TestLlmSettings:
    def test_current_engine_and_providers(self, api):
        state = api.get("/api/settings/llm").json()
        assert (state["active"], state["fallback_chain"]) == ("mock", [])
        providers = {p["name"]: p for p in state["providers"]}
        assert list(providers) == ["ollama", "claude", "mock"]
        assert providers["claude"]["configured"] is False and providers["mock"]["healthy"] is True

    def test_switching_the_engine_at_runtime(self, api):
        state = api.put("/api/settings/llm", json={"provider": "ollama"}).json()
        assert state["active"] == "ollama" == api.container.llm.active
        assert api.get("/api/config").json()["llm_provider"] == "ollama"
        assert api.put("/api/settings/llm", json={"provider": "gpt"}).status_code == 422
        assert api.put("/api/settings/llm", json={"provider": "mock"}).json()["active"] == "mock"

    @pytest.mark.parametrize(("provider", "healthy", "configured"), [("mock", True, True), ("claude", False, False)])
    def test_connection_test(self, api, provider, healthy, configured):
        status = api.post(f"/api/settings/llm/{provider}/test").json()
        assert (status["name"], status["healthy"], status["configured"]) == (provider, healthy, configured)

    def test_connection_test_rejects_unknown_providers(self, api):
        assert api.post("/api/settings/llm/gpt/test").status_code == 422


# ---------------------------------------------------------------- dashboard


def test_dashboard_for_an_employee_and_a_manager(api):
    paid = submitted_claim(api, files=("uber_ride.pdf",), purpose="Airport transfer")
    api.post(f"/api/approvals/{paid['id']}", "manager", json={"decision": "approve"})
    api.settle()
    in_review = submitted_claim(api, files=("apollo_pharmacy_bill.pdf",), purpose="Medicines")
    ready = ready_claim(api, files=("jiofiber_broadband_bill.pdf",), purpose="Home internet")
    returned = submitted_claim(api, files=("indian_oil_bike_fuel.pdf",), purpose="Site visit")
    api.post(f"/api/approvals/{returned['id']}", "manager", json={"decision": "reject"})
    api.create_claim(title="Empty draft")
    submitted_claim(api, "priya")

    dashboard = api.get("/api/dashboard").json()
    assert dashboard["counts"] == {"paid": 1, "submitted": 1, "ready": 1, "rejected": 1, "draft": 1}
    assert (dashboard["drafts"], dashboard["ready_to_submit"], dashboard["pending_questions"]) == (2, 1, 0)
    assert dashboard["in_flight_amount"] == in_review["total_reimbursable"] == 284.0
    assert dashboard["reimbursed_amount"] == paid["total_reimbursable"] == 827.3
    assert dashboard["receipts_processed"] == 4
    assert [(c["category"], c["total"]) for c in dashboard["by_category"]] == [  # the returned fuel bill is left out
        ("broadband", 1178.82), ("local_conveyance", 827.3), ("medical", 284.0)]
    assert dashboard["recent"][0]["title"] == "Empty draft" and len(dashboard["recent"]) == 5
    assert dashboard["pending_approvals"] == 0 and ready["status"] == "ready"

    assert api.get("/api/dashboard", "manager").json()["pending_approvals"] == 2  # Aarav's and Priya's


# ---------------------------------------------------------------- lifespan


def test_startup_resumes_interrupted_work(api_factory):
    seeded = {}

    def seed(container):
        employee = container.users.get(EMPLOYEE_ID)
        approved = make_claim(make_receipt(), title="Approved before restart", status=ClaimStatus.APPROVED,
                              reference_no=f"EXP-{YEAR}-00001", total_reimbursable=450.0)
        container.claims.save(approved)

        interrupted = container.agent.create_claim(employee, "Interrupted", "Airport transfer")
        receipt = make_receipt(claim_id=interrupted.id, stage=ReceiptStage.EXTRACTING, file_name="uber_ride.pdf")
        path = container.agent.receipt_path(interrupted, receipt)
        path.parent.mkdir(parents=True)
        path.write_bytes(sample_pdf("uber_ride.pdf"))
        interrupted.receipts.append(receipt)
        interrupted.status = ClaimStatus.PROCESSING
        container.claims.save(interrupted)
        seeded.update(approved=approved.id, interrupted=interrupted.id)

    api = api_factory(setup=seed)
    api.settle()

    assert api.claim(seeded["approved"])["status"] == "paid"
    resumed = api.claim(seeded["interrupted"])
    assert resumed["receipts"][0]["stage"] == "completed" and resumed["receipts"][0]["data"]["vendor"] == "Uber India"
    assert resumed["status"] == "ready"
