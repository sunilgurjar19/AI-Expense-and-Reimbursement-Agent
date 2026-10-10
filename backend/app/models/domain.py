"""Domain models persisted by the repositories."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


# --------------------------------------------------------------------------- users


class User(BaseModel):
    id: str
    username: str
    password: str
    name: str
    email: str
    role: Literal["employee", "manager"]
    department: str
    employee_code: str
    manager_id: str | None = None
    cost_center: str | None = None


# ------------------------------------------------------------------------ receipts


class ReceiptStage(StrEnum):
    """Processing pipeline stages, in order."""

    UPLOADED = "uploaded"
    READING = "reading"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    CATEGORISING = "categorising"
    VALIDATING = "validating"
    DUPLICATE_CHECK = "duplicate_check"
    COMPLETED = "completed"
    FAILED = "failed"


PIPELINE_STAGES: list[ReceiptStage] = [
    ReceiptStage.UPLOADED,
    ReceiptStage.READING,
    ReceiptStage.EXTRACTING,
    ReceiptStage.VERIFYING,
    ReceiptStage.CATEGORISING,
    ReceiptStage.VALIDATING,
    ReceiptStage.DUPLICATE_CHECK,
    ReceiptStage.COMPLETED,
]


class ReceiptStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    NEEDS_INFO = "needs_info"
    QUESTIONABLE = "questionable"
    EXCLUDED = "excluded"
    FAILED = "failed"


Severity = Literal["info", "warning", "error"]


class Flag(BaseModel):
    code: str
    severity: Severity
    message: str


class LineItem(BaseModel):
    description: str
    amount: float | None = None
    quantity: float | None = None
    unit_price: float | None = None


class ExpenseData(BaseModel):
    """Structured information extracted from (or added to) a receipt."""

    vendor: str | None = None  # in English / Latin script
    vendor_local: str | None = None  # as printed, in the original script (e.g. Devanagari)
    language: str | None = None  # main language of the document, e.g. "Hindi"
    date: str | None = None  # ISO yyyy-mm-dd
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
    line_items: list[LineItem] = Field(default_factory=list)


class Receipt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rcpt"))
    claim_id: str
    file_name: str
    stored_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime = Field(default_factory=utcnow)

    stage: ReceiptStage = ReceiptStage.UPLOADED
    progress: int = 0
    status: ReceiptStatus = ReceiptStatus.PROCESSING
    error: str | None = None

    data: ExpenseData = Field(default_factory=ExpenseData)
    confidence: dict[str, float] = Field(default_factory=dict)
    confirmed_fields: list[str] = Field(default_factory=list)
    is_receipt: bool = True
    extraction_source: str | None = None
    extraction_notes: str | None = None
    read_warning: str | None = None  # the document couldn't actually be read (e.g. photo + offline engine)

    amount_in_base: float | None = None
    reimbursable_amount: float | None = None
    flags: list[Flag] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    duplicate_note: str | None = None  # where the original lives, for the UI
    duplicate_acknowledged: bool = False
    justification: str | None = None
    excluded: bool = False
    purpose_inherited: bool = False  # business_purpose copied from the claim's remarks


# ----------------------------------------------------------------------- questions


QuestionType = Literal["text", "number", "date", "select", "choice"]


class Question(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    key: str  # stable identity "<receipt_id|claim>:<kind>"
    receipt_id: str | None = None
    kind: str  # field name, or "duplicate" / "justification" / "purpose" / "confirm_amount"
    prompt: str
    type: QuestionType = "text"
    options: list[dict[str, str]] = Field(default_factory=list)
    default: Any = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------- chat/claim


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Literal["agent", "user", "system"]
    text: str
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    PROCESSING = "processing"
    NEEDS_ATTENTION = "needs_attention"
    READY = "ready"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


EDITABLE_STATUSES = {
    ClaimStatus.DRAFT,
    ClaimStatus.PROCESSING,
    ClaimStatus.NEEDS_ATTENTION,
    ClaimStatus.READY,
}


class TimelineEvent(BaseModel):
    status: str
    label: str
    actor: str
    note: str | None = None
    at: datetime = Field(default_factory=utcnow)


class ChecklistItem(BaseModel):
    key: str
    label: str
    done: bool


class CategoryGroup(BaseModel):
    category: str
    label: str
    icon: str
    count: int
    total: float


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clm"))
    user_id: str
    title: str = "New expense claim"
    title_is_auto: bool = True
    purpose: str | None = None
    purpose_source: Literal["user", "agent"] | None = None
    purpose_inferring: bool = False
    status: ClaimStatus = ClaimStatus.DRAFT
    currency: str = "INR"
    reference_no: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    submitted_at: datetime | None = None

    receipts: list[Receipt] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)

    # Derived values, recomputed by ClaimService.
    total_claimed: float = 0
    total_reimbursable: float = 0
    readiness: int = 0
    checklist: list[ChecklistItem] = Field(default_factory=list)
    groups: list[CategoryGroup] = Field(default_factory=list)
    period_start: str | None = None
    period_end: str | None = None

    @model_validator(mode="after")
    def _legacy_purpose_is_user_written(self) -> "Claim":
        # Claims saved before purpose_source existed: any purpose was typed by the employee.
        if self.purpose and self.purpose_source is None:
            self.purpose_source = "user"
        return self

    def receipt(self, receipt_id: str) -> Receipt | None:
        return next((r for r in self.receipts if r.id == receipt_id), None)

    @property
    def active_receipts(self) -> list[Receipt]:
        return [r for r in self.receipts if not r.excluded]

    @property
    def is_editable(self) -> bool:
        return self.status in EDITABLE_STATUSES


# ------------------------------------------------------------------- notifications


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ntf"))
    user_id: str
    level: Literal["info", "success", "warning", "error"] = "info"
    title: str
    message: str
    link: str | None = None
    read: bool = False
    created_at: datetime = Field(default_factory=utcnow)
