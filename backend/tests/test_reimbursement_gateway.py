"""MockReimbursementGateway: references, manager approval, auto-approval, rejection and delayed payout."""

from datetime import datetime

import pytest

from app.core.config import ReimbursementSection
from app.core.events import EventBus
from app.models.domain import ClaimStatus
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService
from app.services.reimbursement_gateway import GatewayError, MockReimbursementGateway
from tests.helpers import BACKEND_DIR, EMPLOYEE_ID, MANAGER_ID, PRIYA_ID, drain, make_claim, make_receipt

YEAR = f"{datetime.now():%Y}"


@pytest.fixture
def users() -> UserRepository:
    return UserRepository(BACKEND_DIR / "data" / "users.json")


@pytest.fixture
def notifications(store) -> NotificationService:
    return NotificationService(NotificationRepository(store, max_per_user=200), EventBus())


@pytest.fixture
def published() -> list:
    return []


@pytest.fixture
def make_gateway(claim_repo, users, notifications, published):
    def factory(**config) -> MockReimbursementGateway:
        section = ReimbursementSection(**{"payout_delay_seconds": 0, **config})
        return MockReimbursementGateway(section, "INR", claim_repo, users, notifications, published.append)

    return factory


@pytest.fixture
def ready_claim(claim_repo):
    def factory(user_id: str = EMPLOYEE_ID, amount: float = 1200.0, title: str = "Pune trip"):
        claim = make_claim(make_receipt(total_amount=amount), user_id=user_id, title=title, purpose="Client visit",
                           status=ClaimStatus.READY, total_reimbursable=amount)
        return claim_repo.save(claim)

    return factory


def timeline(claim) -> list[tuple[str, str]]:
    return [(e.status, e.actor) for e in claim.timeline]


def titles(notifications, user_id) -> list[str]:
    return [n.title for n in notifications.list(user_id)]


class TestSubmit:
    @pytest.mark.parametrize("status", [ClaimStatus.DRAFT, ClaimStatus.NEEDS_ATTENTION, ClaimStatus.SUBMITTED])
    async def test_only_ready_claims_can_be_submitted(self, make_gateway, ready_claim, users, status):
        claim = ready_claim()
        claim.status = status
        with pytest.raises(GatewayError, match="Only claims that are ready can be submitted"):
            make_gateway().submit(claim, users.get(EMPLOYEE_ID))

    async def test_submission_issues_a_reference_and_asks_the_manager(self, make_gateway, ready_claim, users,
                                                                      notifications, claim_repo):
        gateway, claim = make_gateway(), ready_claim()

        gateway.submit(claim, users.get(EMPLOYEE_ID))

        assert claim.status == ClaimStatus.SUBMITTED and claim.submitted_at is not None
        assert claim.reference_no == f"EXP-{YEAR}-00001"
        assert timeline(claim) == [("submitted", "Aarav Sharma"), ("manager_review", "Meera Iyer")]
        assert claim.timeline[0].note == f"Reference EXP-{YEAR}-00001"
        (receipt_note,) = notifications.list(EMPLOYEE_ID)
        assert (receipt_note.title, receipt_note.level, receipt_note.link) == (
            "Claim submitted 🚀", "success", f"/claims/{claim.id}")
        assert receipt_note.message == f"Pune trip (INR 1,200.00) was submitted as EXP-{YEAR}-00001."
        (approval,) = notifications.list(MANAGER_ID)
        assert (approval.title, approval.link) == ("Approval needed", f"/approvals/{claim.id}")
        assert approval.message == "Aarav Sharma submitted Pune trip for INR 1,200.00."
        assert claim_repo.get(claim.id).status == ClaimStatus.SUBMITTED
        assert gateway._tasks == set()  # nothing is paid before approval

    async def test_reference_numbers_count_up_with_the_configured_prefix(self, make_gateway, ready_claim, users):
        gateway, employee = make_gateway(reference_prefix="FIN"), users.get(EMPLOYEE_ID)
        first = gateway.submit(ready_claim(title="A"), employee)
        second = gateway.submit(ready_claim(title="B"), employee)
        assert (first.reference_no, second.reference_no) == (f"FIN-{YEAR}-00001", f"FIN-{YEAR}-00002")

    @pytest.mark.parametrize(
        ("config", "submitter", "amount"),
        [
            ({"manager_approval_required": False}, EMPLOYEE_ID, 1200.0),
            ({"auto_approve_below": 5000}, EMPLOYEE_ID, 1200.0),
            ({"auto_approve_below": 5000}, EMPLOYEE_ID, 5000.0),  # the threshold itself is included
            ({}, MANAGER_ID, 1200.0),  # nobody above the manager: straight through
        ],
        ids=["approval-disabled", "below-threshold", "at-threshold", "no-manager"],
    )
    async def test_auto_approval_and_payout(self, make_gateway, ready_claim, users, notifications, published,
                                            config, submitter, amount):
        gateway = make_gateway(**config)
        claim = ready_claim(user_id=submitter, amount=amount)

        gateway.submit(claim, users.get(submitter))
        assert claim.status == ClaimStatus.APPROVED
        assert timeline(claim)[1:] == [("approved", "Policy engine (auto-approval)"), ("finance_processing", "Finance (mock)")]

        await drain(gateway)
        assert claim.status == ClaimStatus.PAID
        assert timeline(claim)[-1] == ("paid", "Finance (mock)")
        assert titles(notifications, submitter)[0] == "Money on its way 💸"
        assert published == [claim]

    @pytest.mark.parametrize("amount", [0.0, 7500.0], ids=["nothing-reimbursable", "above-threshold"])
    async def test_claims_outside_the_auto_approval_band_wait_for_the_manager(self, make_gateway, ready_claim, users,
                                                                              amount):
        claim = ready_claim(amount=amount)
        make_gateway(auto_approve_below=5000).submit(claim, users.get(EMPLOYEE_ID))
        assert claim.status == ClaimStatus.SUBMITTED


class TestDecide:
    async def test_only_submitted_claims_can_be_decided(self, make_gateway, ready_claim, users):
        with pytest.raises(GatewayError, match="not awaiting approval"):
            make_gateway().decide(ready_claim(), users.get(MANAGER_ID), approve=True, comment=None)

    @pytest.mark.parametrize("owner", [EMPLOYEE_ID, "u-gone"], ids=["someone-elses-report", "unknown-employee"])
    async def test_only_the_employees_manager_can_decide(self, make_gateway, ready_claim, users, owner):
        gateway = make_gateway()
        claim = ready_claim(user_id=owner)
        claim.status = ClaimStatus.SUBMITTED
        with pytest.raises(GatewayError, match="not the approver"):
            gateway.decide(claim, users.get(PRIYA_ID), approve=True, comment=None)

    async def test_approval_queues_the_payout(self, make_gateway, ready_claim, users, notifications, published,
                                              claim_repo):
        gateway, employee, manager = make_gateway(), users.get(EMPLOYEE_ID), users.get(MANAGER_ID)
        claim = gateway.submit(ready_claim(), employee)

        gateway.decide(claim, manager, approve=True, comment="Looks good")

        assert claim.status == ClaimStatus.APPROVED
        assert timeline(claim)[-2:] == [("approved", "Meera Iyer"), ("finance_processing", "Finance (mock)")]
        assert claim.timeline[-2].note == "Looks good"
        assert titles(notifications, EMPLOYEE_ID)[0] == "Claim approved ✅"

        await drain(gateway)
        assert claim_repo.get(claim.id).status == ClaimStatus.PAID
        assert claim.timeline[-1].note == "INR 1,200.00 transferred"
        assert notifications.list(EMPLOYEE_ID)[0].message == (
            f"INR 1,200.00 for EXP-{YEAR}-00001 has been paid out.")
        assert published == [claim]

    @pytest.mark.parametrize(("comment", "shown"), [("Missing hotel bill", "Missing hotel bill"), (None, "no comment")])
    async def test_rejection_returns_the_claim_to_the_employee(self, make_gateway, ready_claim, users, notifications,
                                                               comment, shown):
        gateway = make_gateway()
        claim = gateway.submit(ready_claim(), users.get(EMPLOYEE_ID))

        gateway.decide(claim, users.get(MANAGER_ID), approve=False, comment=comment)

        assert claim.status == ClaimStatus.REJECTED
        assert timeline(claim)[-1] == ("rejected", "Meera Iyer") and claim.timeline[-1].note == comment
        latest = notifications.list(EMPLOYEE_ID)[0]
        assert (latest.title, latest.level) == ("Claim returned", "error")
        assert latest.message == f"Meera Iyer returned EXP-{YEAR}-00001: {shown}. Reopen it to fix and resubmit."
        assert gateway._tasks == set()


class TestPayout:
    async def test_payout_is_skipped_if_the_claim_changed_meanwhile(self, make_gateway, ready_claim, users, published):
        gateway = make_gateway(manager_approval_required=False)
        changed = gateway.submit(ready_claim(title="Changed"), users.get(EMPLOYEE_ID))
        deleted = gateway.submit(ready_claim(title="Deleted"), users.get(EMPLOYEE_ID))
        changed.status = ClaimStatus.REJECTED
        gateway._claims.delete(deleted.id)

        await drain(gateway)

        assert changed.status == ClaimStatus.REJECTED and "paid" not in [e.status for e in changed.timeline]
        assert published == []

    async def test_pending_payouts_resume_after_a_restart(self, make_gateway, ready_claim, claim_repo):
        approved, submitted = ready_claim(title="Approved"), ready_claim(title="Submitted")
        approved.status, submitted.status = ClaimStatus.APPROVED, ClaimStatus.SUBMITTED
        gateway = make_gateway()

        gateway.resume_pending_payouts()
        assert len(gateway._tasks) == 1
        await drain(gateway)

        assert claim_repo.get(approved.id).status == ClaimStatus.PAID
        assert claim_repo.get(submitted.id).status == ClaimStatus.SUBMITTED


@pytest.mark.parametrize("scenario", ["returned-claim-resubmitted", "reopened-claim-deleted"])
async def test_reference_numbers_are_never_reused(make_gateway, ready_claim, users, claim_repo, scenario):
    gateway, employee, manager = make_gateway(), users.get(EMPLOYEE_ID), users.get(MANAGER_ID)
    first = gateway.submit(ready_claim(title="A"), employee)
    issued = [first.reference_no]
    if scenario == "returned-claim-resubmitted":
        gateway.decide(first, manager, approve=False, comment="Add the hotel bill")
        first.status = ClaimStatus.READY  # what POST /reopen + the employee's fixes lead to
        issued.append(gateway.submit(first, employee).reference_no)
    else:
        issued.append(gateway.submit(ready_claim(title="B"), employee).reference_no)
        gateway.decide(first, manager, approve=False, comment="Wrong trip")
        first.status = ClaimStatus.NEEDS_ATTENTION  # reopened claims are editable, so they can be deleted
        claim_repo.delete(first.id)

    latest = gateway.submit(ready_claim(title="C"), employee)

    assert latest.reference_no not in issued


async def test_a_resubmitted_claim_keeps_its_reference(make_gateway, ready_claim, users):
    gateway, employee, manager = make_gateway(), users.get(EMPLOYEE_ID), users.get(MANAGER_ID)
    claim = gateway.submit(ready_claim(title="A"), employee)
    reference = claim.reference_no
    gateway.decide(claim, manager, approve=False, comment="Add the hotel bill")
    claim.status = ClaimStatus.READY  # reopened and fixed

    assert gateway.submit(claim, employee).reference_no == reference
    assert [e.note for e in claim.timeline if e.status == "submitted"] == [f"Reference {reference}"] * 2
