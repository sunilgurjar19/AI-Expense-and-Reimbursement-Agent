from collections import Counter, defaultdict

from fastapi import APIRouter

from app.api.deps import AppContainer, CurrentUser
from app.models.api import ClaimSummary
from app.models.domain import ClaimStatus, EDITABLE_STATUSES

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

IN_FLIGHT = {ClaimStatus.SUBMITTED, ClaimStatus.APPROVED}


@router.get("")
def summary(user: CurrentUser, app: AppContainer) -> dict:
    claims = app.claims.for_user(user.id)
    by_status = Counter(c.status.value for c in claims)

    by_category: dict[str, float] = defaultdict(float)
    for claim in claims:
        if claim.status != ClaimStatus.REJECTED:
            for group in claim.groups:
                by_category[group.category] += group.total

    categories = []
    for key, total in sorted(by_category.items(), key=lambda kv: -kv[1]):
        rule = app.policy.category(key)
        categories.append({
            "category": key,
            "label": rule.label if rule else key,
            "icon": rule.icon if rule else "🧾",
            "total": round(total, 2),
        })

    result = {
        "currency": app.settings.app.base_currency,
        "counts": dict(by_status),
        "drafts": sum(1 for c in claims if c.status in EDITABLE_STATUSES),
        "pending_questions": sum(len(c.questions) for c in claims if c.status in EDITABLE_STATUSES),
        "ready_to_submit": by_status.get(ClaimStatus.READY.value, 0),
        "in_flight_amount": round(sum(c.total_reimbursable for c in claims if c.status in IN_FLIGHT), 2),
        "reimbursed_amount": round(sum(c.total_reimbursable for c in claims if c.status == ClaimStatus.PAID), 2),
        "receipts_processed": sum(len(c.receipts) for c in claims),
        "by_category": categories,
        "recent": [ClaimSummary.from_claim(c) for c in claims[:6]],
        "pending_approvals": 0,
    }
    if user.role == "manager":
        team = {u.id for u in app.users.reports_of(user.id)}
        result["pending_approvals"] = sum(
            1 for c in app.claims.for_users(team) if c.status == ClaimStatus.SUBMITTED
        )
    return result
