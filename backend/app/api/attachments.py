"""Serving receipt documents: single files (view or download) and a zip of a whole claim."""

import io
import zipfile
from pathlib import Path

from fastapi import HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.container import Container
from app.models.domain import Claim


def receipt_file_response(app: Container, claim: Claim, receipt_id: str, download: bool) -> FileResponse:
    receipt = claim.receipt(receipt_id)
    path = app.agent.receipt_path(claim, receipt) if receipt else None
    if receipt is None or path is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(
        path,
        media_type=receipt.mime_type,
        filename=receipt.file_name,
        content_disposition_type="attachment" if download else "inline",
    )


def attachments_zip_response(app: Container, claim: Claim) -> StreamingResponse:
    """All documents on the claim (excluded ones left out), numbered in upload order."""
    buffer = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for receipt in claim.active_receipts:
            path = app.agent.receipt_path(claim, receipt)
            if path.exists():
                added += 1
                archive.write(path, arcname=f"{added:02d}_{Path(receipt.file_name).name}")
    if not added:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This claim has no documents")

    buffer.seek(0)
    filename = f"{claim.reference_no or claim.id}-receipts.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
