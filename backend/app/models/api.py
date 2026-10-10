"""Request / response schemas for the HTTP API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.domain import Claim, ClaimStatus, User


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserPublic(BaseModel):
    id: str
    username: str
    name: str
    email: str
    role: str
    department: str
    employee_code: str
    cost_center: str | None = None

    @classmethod
    def from_user(cls, user: User) -> "UserPublic":
        return cls(**user.model_dump(exclude={"password", "manager_id"}))


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class DemoUser(BaseModel):
    username: str
    password: str
    name: str
    role: str


class ClaimCreate(BaseModel):
    title: str | None = None
    purpose: str | None = None


class ClaimUpdate(BaseModel):
    title: str | None = None
    purpose: str | None = None


class ReceiptUpdate(BaseModel):
    """Manual edits to a receipt. Only provided fields are applied."""

    vendor: str | None = None
    date: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    tax_amount: float | None = None
    category: str | None = None
    payment_method: str | None = None
    invoice_number: str | None = None
    location: str | None = None
    description: str | None = None
    business_purpose: str | None = None
    attendees: str | None = None
    justification: str | None = None
    excluded: bool | None = None


class AnswerRequest(BaseModel):
    answer: Any


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ClaimSummary(BaseModel):
    id: str
    title: str
    status: ClaimStatus
    reference_no: str | None
    currency: str
    total_claimed: float
    total_reimbursable: float
    readiness: int
    receipt_count: int
    pending_questions: int
    period_start: str | None
    period_end: str | None
    created_at: Any
    updated_at: Any
    submitted_at: Any
    owner_name: str | None = None

    @classmethod
    def from_claim(cls, claim: Claim, owner_name: str | None = None) -> "ClaimSummary":
        return cls(
            id=claim.id,
            title=claim.title,
            status=claim.status,
            reference_no=claim.reference_no,
            currency=claim.currency,
            total_claimed=claim.total_claimed,
            total_reimbursable=claim.total_reimbursable,
            readiness=claim.readiness,
            receipt_count=len(claim.active_receipts),
            pending_questions=len(claim.questions),
            period_start=claim.period_start,
            period_end=claim.period_end,
            created_at=claim.created_at,
            updated_at=claim.updated_at,
            submitted_at=claim.submitted_at,
            owner_name=owner_name,
        )


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


class LLMSettingsUpdate(BaseModel):
    provider: Literal["ollama", "claude", "mock"]
