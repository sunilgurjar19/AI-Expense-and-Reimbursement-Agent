from fastapi import APIRouter

from app.api.deps import AppContainer, CurrentUser
from app.models.domain import PIPELINE_STAGES

router = APIRouter(tags=["meta"])


@router.get("/config")
def public_config(app: AppContainer, _: CurrentUser) -> dict:
    """Everything the UI needs to render policy-aware screens."""
    settings, policy = app.settings, app.policy
    return {
        "app_name": settings.app.name,
        "agent_name": settings.app.agent_name,
        "company": settings.app.company,
        "currency": settings.app.base_currency,
        "llm_provider": app.llm.active,
        "max_upload_mb": settings.storage.max_upload_mb,
        "allowed_extensions": settings.storage.allowed_extensions,
        "pipeline_stages": [s.value for s in PIPELINE_STAGES],
        "categories": [c.model_dump(exclude={"keywords"}) for c in policy.categories],
        "currencies": list(policy.fx_rates),
        "policy": {
            "max_receipt_age_days": policy.max_receipt_age_days,
            "receipt_required_above": policy.receipt_required_above,
            "claim_requires_purpose": policy.claim_requires_purpose,
            "blocked_keywords": policy.blocked_keywords,
        },
    }


@router.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok"}
