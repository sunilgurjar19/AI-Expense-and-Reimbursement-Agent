from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.attachments import attachments_zip_response, receipt_file_response
from app.api.deps import AppContainer, Manager
from app.container import Container
from app.models.api import ApprovalDecision, ClaimSummary
from app.models.domain import Claim, ClaimStatus

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _team_claim(claim_id: str, manager_id: str, app: Container) -> Claim:
    claim = app.claims.get(claim_id)
    team = {u.id for u in app.users.reports_of(manager_id)}
    if claim is None or claim.user_id not in team or claim.status == ClaimStatus.DRAFT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    return claim


@router.get("", response_model=list[ClaimSummary])
def list_team_claims(manager: Manager, app: AppContainer) -> list[ClaimSummary]:
    team = {u.id: u for u in app.users.reports_of(manager.id)}
    visible = {ClaimStatus.SUBMITTED, ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.PAID}
    return [
        ClaimSummary.from_claim(c, owner_name=team[c.user_id].name)
        for c in app.claims.for_users(set(team))
        if c.status in visible
    ]


@router.get("/{claim_id}", response_model=Claim)
def get_team_claim(claim_id: str, manager: Manager, app: AppContainer) -> Claim:
    return _team_claim(claim_id, manager.id, app)


@router.post("/{claim_id}", response_model=Claim)
async def decide(claim_id: str, body: ApprovalDecision, manager: Manager, app: AppContainer) -> Claim:
    claim = _team_claim(claim_id, manager.id, app)
    claim = app.gateway.decide(claim, manager, approve=body.decision == "approve", comment=body.comment)
    app.publish_claim(claim)
    return claim


@router.get("/{claim_id}/receipts/{receipt_id}/file")
def receipt_file(
    claim_id: str, receipt_id: str, manager: Manager, app: AppContainer, download: bool = False
) -> FileResponse:
    return receipt_file_response(app, _team_claim(claim_id, manager.id, app), receipt_id, download)


@router.get("/{claim_id}/attachments.zip")
def attachments_zip(claim_id: str, manager: Manager, app: AppContainer) -> StreamingResponse:
    return attachments_zip_response(app, _team_claim(claim_id, manager.id, app))
