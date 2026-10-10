"""Mock of the corporate reimbursement / finance platform.

It issues reference numbers, routes claims to the employee's manager and
simulates finance paying out approved claims after a configurable delay.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from app.core.config import ReimbursementSection
from app.models.domain import Claim, ClaimStatus, TimelineEvent, User, utcnow
from app.repositories.claim_repository import ClaimRepository
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    pass


class MockReimbursementGateway:
    def __init__(
        self,
        config: ReimbursementSection,
        currency: str,
        claims: ClaimRepository,
        users: UserRepository,
        notifications: NotificationService,
        publish: Callable[[Claim], None],
    ) -> None:
        self._config = config
        self._currency = currency
        self._claims = claims
        self._users = users
        self._notifications = notifications
        self._publish = publish
        self._tasks: set[asyncio.Task] = set()

    def resume_pending_payouts(self) -> None:
        """Re-schedule payouts for approved claims after a restart."""
        for claim in self._claims.all():
            if claim.status == ClaimStatus.APPROVED:
                self._schedule_payout(claim.id)

    # ---------------------------------------------------------------- submit

    def submit(self, claim: Claim, employee: User) -> Claim:
        if claim.status != ClaimStatus.READY:
            raise GatewayError("Only claims that are ready can be submitted")

        if not claim.reference_no:  # a returned claim keeps its reference when resubmitted
            claim.reference_no = f"{self._config.reference_prefix}-{datetime.now():%Y}-{self._claims.next_sequence():05d}"
        claim.status = ClaimStatus.SUBMITTED
        claim.submitted_at = utcnow()
        claim.timeline.append(
            TimelineEvent(status="submitted", label="Submitted to finance system", actor=employee.name,
                          note=f"Reference {claim.reference_no}")
        )
        amount = f"{self._currency} {claim.total_reimbursable:,.2f}"
        self._notifications.notify(
            employee.id, "Claim submitted 🚀",
            f"{claim.title} ({amount}) was submitted as {claim.reference_no}.",
            level="success", link=f"/claims/{claim.id}",
        )

        manager = self._users.get(employee.manager_id or "")
        auto = 0 < claim.total_reimbursable <= self._config.auto_approve_below
        if not self._config.manager_approval_required or auto or manager is None:
            self._approve(claim, actor="Policy engine (auto-approval)", note="Within auto-approval threshold")
        else:
            claim.timeline.append(
                TimelineEvent(status="manager_review", label="Awaiting manager approval", actor=manager.name)
            )
            self._notifications.notify(
                manager.id, "Approval needed",
                f"{employee.name} submitted {claim.title} for {amount}.",
                level="info", link=f"/approvals/{claim.id}",
            )
        return self._claims.save(claim)

    # -------------------------------------------------------------- decision

    def decide(self, claim: Claim, manager: User, approve: bool, comment: str | None) -> Claim:
        if claim.status != ClaimStatus.SUBMITTED:
            raise GatewayError("This claim is not awaiting approval")
        employee = self._users.get(claim.user_id)
        if employee is None or employee.manager_id != manager.id:
            raise GatewayError("You are not the approver for this claim")

        if approve:
            self._approve(claim, actor=manager.name, note=comment)
        else:
            claim.status = ClaimStatus.REJECTED
            claim.timeline.append(
                TimelineEvent(status="rejected", label="Returned by manager", actor=manager.name, note=comment)
            )
            self._notifications.notify(
                claim.user_id, "Claim returned",
                f"{manager.name} returned {claim.reference_no}: {comment or 'no comment'}. Reopen it to fix and resubmit.",
                level="error", link=f"/claims/{claim.id}",
            )
        return self._claims.save(claim)

    def _approve(self, claim: Claim, actor: str, note: str | None) -> None:
        claim.status = ClaimStatus.APPROVED
        claim.timeline.append(TimelineEvent(status="approved", label="Approved", actor=actor, note=note))
        claim.timeline.append(
            TimelineEvent(status="finance_processing", label="Queued for payout", actor="Finance (mock)")
        )
        self._notifications.notify(
            claim.user_id, "Claim approved ✅",
            f"{claim.reference_no} was approved by {actor}. Finance is processing the payout.",
            level="success", link=f"/claims/{claim.id}",
        )
        self._schedule_payout(claim.id)

    def _schedule_payout(self, claim_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._payout_later(claim_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _payout_later(self, claim_id: str) -> None:
        await asyncio.sleep(self._config.payout_delay_seconds)
        claim = self._claims.get(claim_id)
        if claim is None or claim.status != ClaimStatus.APPROVED:
            return
        claim.status = ClaimStatus.PAID
        claim.timeline.append(
            TimelineEvent(status="paid", label="Reimbursed to salary account", actor="Finance (mock)",
                          note=f"{self._currency} {claim.total_reimbursable:,.2f} transferred")
        )
        self._claims.save(claim)
        self._publish(claim)
        self._notifications.notify(
            claim.user_id, "Money on its way 💸",
            f"{self._currency} {claim.total_reimbursable:,.2f} for {claim.reference_no} has been paid out.",
            level="success", link=f"/claims/{claim.id}",
        )
