import csv
import io

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.attachments import attachments_zip_response, receipt_file_response
from app.api.deps import AppContainer, CurrentUser, OwnedClaim
from app.models.api import (
    AnswerRequest,
    ChatRequest,
    ClaimCreate,
    ClaimSummary,
    ClaimUpdate,
    ReceiptUpdate,
)
from app.models.domain import Claim, ClaimStatus, Receipt, TimelineEvent

router = APIRouter(prefix="/claims", tags=["claims"])


def _receipt_or_404(claim: Claim, receipt_id: str) -> Receipt:
    receipt = claim.receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return receipt


@router.get("", response_model=list[ClaimSummary])
def list_claims(user: CurrentUser, app: AppContainer) -> list[ClaimSummary]:
    return [ClaimSummary.from_claim(c) for c in app.claims.for_user(user.id)]


@router.post("", response_model=Claim, status_code=status.HTTP_201_CREATED)
def create_claim(body: ClaimCreate, user: CurrentUser, app: AppContainer) -> Claim:
    return app.agent.create_claim(user, body.title, body.purpose)


@router.get("/{claim_id}", response_model=Claim)
def get_claim(claim: OwnedClaim) -> Claim:
    return claim


@router.patch("/{claim_id}", response_model=Claim)
def update_claim(body: ClaimUpdate, claim: OwnedClaim, app: AppContainer) -> Claim:
    if not claim.is_editable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Submitted claims can't be edited")
    if body.title is not None and body.title.strip():
        claim.title, claim.title_is_auto = body.title.strip()[:120], False
    if body.purpose is not None:
        app.claim_service.set_purpose(claim, body.purpose)
    app.agent.save(claim)
    return claim


@router.delete("/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_claim(claim: OwnedClaim, app: AppContainer) -> None:
    app.agent.delete_claim(claim)


# ------------------------------------------------------------------- receipts


@router.post("/{claim_id}/receipts", response_model=list[Receipt], status_code=status.HTTP_202_ACCEPTED)
async def upload_receipts(
    claim: OwnedClaim, app: AppContainer, files: list[UploadFile] = File(...)
) -> list[Receipt]:
    payload = [(f.filename or "receipt", await f.read(), f.content_type) for f in files]
    return app.agent.add_receipts(claim, payload)


@router.patch("/{claim_id}/receipts/{receipt_id}", response_model=Claim)
def update_receipt(receipt_id: str, body: ReceiptUpdate, claim: OwnedClaim, app: AppContainer) -> Claim:
    if not claim.is_editable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Submitted claims can't be edited")
    app.claim_service.apply_update(_receipt_or_404(claim, receipt_id), body)
    app.agent.save(claim)
    return claim


@router.post("/{claim_id}/receipts/{receipt_id}/retry", response_model=Claim)
async def retry_receipt(receipt_id: str, claim: OwnedClaim, app: AppContainer) -> Claim:
    app.agent.retry_receipt(claim, _receipt_or_404(claim, receipt_id))
    return claim


@router.delete("/{claim_id}/receipts/{receipt_id}", response_model=Claim)
def delete_receipt(receipt_id: str, claim: OwnedClaim, app: AppContainer) -> Claim:
    if not claim.is_editable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Submitted claims can't be edited")
    receipt = _receipt_or_404(claim, receipt_id)
    claim.receipts.remove(receipt)
    app.agent.receipt_path(claim, receipt).unlink(missing_ok=True)
    app.agent.save(claim)
    return claim


@router.get("/{claim_id}/receipts/{receipt_id}/file")
def receipt_file(
    receipt_id: str, claim: OwnedClaim, app: AppContainer, download: bool = False
) -> FileResponse:
    return receipt_file_response(app, claim, receipt_id, download)


@router.get("/{claim_id}/attachments.zip")
def attachments_zip(claim: OwnedClaim, app: AppContainer) -> StreamingResponse:
    return attachments_zip_response(app, claim)


# ---------------------------------------------------------------- conversation


@router.post("/{claim_id}/questions/{question_id}/answer", response_model=Claim)
def answer_question(question_id: str, body: AnswerRequest, claim: OwnedClaim, app: AppContainer) -> Claim:
    return app.agent.answer_question(claim, question_id, body.answer)


@router.post("/{claim_id}/chat", response_model=Claim)
async def chat(body: ChatRequest, claim: OwnedClaim, user: CurrentUser, app: AppContainer) -> Claim:
    return await app.agent.chat(claim, user, body.message.strip())


# ------------------------------------------------------------------ lifecycle


@router.post("/{claim_id}/submit", response_model=Claim)
async def submit_claim(claim: OwnedClaim, user: CurrentUser, app: AppContainer) -> Claim:
    app.claim_service.recompute(claim)
    claim = app.gateway.submit(claim, user)
    app.publish_claim(claim)
    return claim


@router.post("/{claim_id}/reopen", response_model=Claim)
def reopen_claim(claim: OwnedClaim, user: CurrentUser, app: AppContainer) -> Claim:
    if claim.status != ClaimStatus.REJECTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only returned claims can be reopened")
    claim.status = ClaimStatus.NEEDS_ATTENTION
    claim.timeline.append(TimelineEvent(status="reopened", label="Reopened for changes", actor=user.name))
    app.agent.save(claim)
    return claim


@router.get("/{claim_id}/export")
def export_claim(claim: OwnedClaim) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Merchant", "Category", "Currency", "Amount", f"Amount ({claim.currency})",
                     f"Reimbursable ({claim.currency})", "Invoice #", "Purpose", "Notes"])
    for r in claim.active_receipts:
        d = r.data
        writer.writerow([d.date, d.vendor, d.category, d.currency, d.total_amount, r.amount_in_base,
                         r.reimbursable_amount, d.invoice_number, d.business_purpose or claim.purpose,
                         "; ".join(f.message for f in r.flags)])
    filename = f"{claim.reference_no or claim.id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
