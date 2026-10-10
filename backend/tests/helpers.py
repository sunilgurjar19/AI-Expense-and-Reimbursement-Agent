"""Factories and test doubles shared by the test-suite.

Imported by ``conftest.py`` *after* it has isolated the environment, so importing ``app`` here is safe.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.models.domain import Claim, ExpenseData, LineItem, Receipt, ReceiptStage
from app.services.llm import LLMError, LLMRequest, LLMResult
from app.services.llm.base import LLMProvider, ProviderStatus

BACKEND_DIR = Path(__file__).resolve().parents[1]
SAMPLES_DIR = BACKEND_DIR / "samples"
POLICY_FILE = BACKEND_DIR / "config" / "policy.yaml"
REAL_STORAGE_DIR = BACKEND_DIR / "storage"

DEMO_PASSWORDS = {"employee": "employee123", "priya": "priya123", "manager": "manager123"}
EMPLOYEE_ID, PRIYA_ID, MANAGER_ID = "u-1001", "u-1002", "u-2001"

_EXPENSE_FIELDS = set(ExpenseData.model_fields)


# ----------------------------------------------------------------------- dates


def iso_days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def recent_weekday(min_days_ago: int = 3) -> str:
    """ISO date of the most recent Mon-Fri at least ``min_days_ago`` days back (no WEEKEND flag)."""
    day = date.today() - timedelta(days=min_days_ago)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def recent_weekend_day(min_days_ago: int = 3) -> str:
    day = date.today() - timedelta(days=min_days_ago)
    while day.weekday() < 5:
        day -= timedelta(days=1)
    return day.isoformat()


def dmy(iso: str) -> str:
    """Day-first rendering used on Indian bills."""
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


# ------------------------------------------------------------------- settings


def make_settings(root: Path, **sections: Any) -> Settings:
    """Settings from config/settings.yaml + the isolated test env, with storage inside ``root``.

    ``sections`` are deep-merged over the YAML/env values, e.g. ``make_settings(tmp, llm={"max_concurrency": 1})``.
    """
    storage = {"database_file": str(root / "db.json"), "upload_dir": str(root / "uploads")}
    storage.update(sections.pop("storage", {}))
    # Page renders are only looked at by vision models; the offline engine reads the text layer, so keep them
    # small (DocumentReader's own tests cover real resolutions).
    pipeline = {"pdf_render_dpi": 36, **sections.pop("pipeline", {})}
    return Settings(_env_file=None, storage=storage, pipeline=pipeline, **sections)


# ------------------------------------------------------------------ factories


def make_receipt(**overrides: Any) -> Receipt:
    """A completed receipt with clean data; any ExpenseData or Receipt field can be overridden."""
    data: dict[str, Any] = {
        "vendor": "Uber India",
        "date": recent_weekday(),
        "total_amount": 450.0,
        "currency": "INR",
        "category": "local_conveyance",
    }
    receipt: dict[str, Any] = {
        "claim_id": "clm-test",
        "file_name": "receipt.pdf",
        "stored_name": f"{uuid4().hex}.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "sha256": uuid4().hex,
        "stage": ReceiptStage.COMPLETED,
        "progress": 100,
    }
    for key, value in overrides.items():
        (data if key in _EXPENSE_FIELDS else receipt)[key] = value
    data["line_items"] = [i if isinstance(i, LineItem) else LineItem(**i) for i in data.get("line_items", [])]
    return Receipt(**receipt, data=ExpenseData(**data))


def make_claim(*receipts: Receipt, **overrides: Any) -> Claim:
    claim = Claim(**{"user_id": EMPLOYEE_ID, **overrides})
    for receipt in receipts:
        receipt.claim_id = claim.id
        claim.receipts.append(receipt)
    return claim


def at(minutes: int) -> datetime:
    """A fixed, ordered upload timestamp (used to control which receipt counts as the original)."""
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)


# ---------------------------------------------------------------- LLM doubles


Reply = str | dict | BaseException | LLMResult | Callable[[LLMRequest], Any]


class ScriptedRegistry:
    """Drop-in for ``LLMRegistry.generate``: replies are scripted per task and every request is recorded.

    A reply may be a str (raw model text), a dict (JSON-encoded), an exception (raised), an ``LLMResult``
    (returned as-is), a callable taking the request, or a list of those consumed in order.
    """

    def __init__(self, replies: dict[str, Reply | list[Reply]] | None = None, provider: str = "fake",
                 fell_back: bool = False, errors: list[str] | None = None) -> None:
        self.replies = dict(replies or {})
        self.provider = provider
        self.fell_back = fell_back
        self.errors = list(errors or [])
        self.requests: list[LLMRequest] = []

    def tasks(self) -> list[str]:
        return [r.task for r in self.requests]

    async def generate(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        if request.task not in self.replies:
            raise AssertionError(f"Unexpected LLM call for task {request.task!r}")
        reply = self.replies[request.task]
        if isinstance(reply, list):
            reply = reply.pop(0)
        if callable(reply) and not isinstance(reply, (BaseException, LLMResult)):
            reply = reply(request)
            if asyncio.iscoroutine(reply):
                reply = await reply
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, LLMResult):
            return reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return LLMResult(text=text, provider=self.provider, fell_back=self.fell_back, errors=list(self.errors))


class ConcurrencyProbe:
    """Tracks how many fake provider calls are in flight at once."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0


class FakeProvider(LLMProvider):
    """A provider whose reply/failure is scripted; optionally sleeps to exercise concurrency limits."""

    def __init__(self, name: str, reply: str = "{}", error: str | None = None, delay: float = 0,
                 probe: ConcurrencyProbe | None = None, raises: BaseException | None = None) -> None:
        self.name = name
        self.label = f"Fake {name}"
        self.reply = reply
        self.error = error
        self.raises = raises
        self.delay = delay
        self.probe = probe
        self.calls: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> str:
        self.calls.append(request)
        if self.probe:
            self.probe.active += 1
            self.probe.peak = max(self.probe.peak, self.probe.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.raises:
                raise self.raises
            if self.error:
                raise LLMError(self.error)
            return self.reply
        finally:
            if self.probe:
                self.probe.active -= 1

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, label=self.label, configured=True, healthy=True)


def llm_request(task: str = "chat", **kwargs: Any) -> LLMRequest:
    return LLMRequest(task=task, system=kwargs.pop("system", "system prompt"),  # type: ignore[arg-type]
                      prompt=kwargs.pop("prompt", "user prompt"), **kwargs)


# ------------------------------------------------------------------ documents


@lru_cache
def sample_generator() -> ModuleType:
    """scripts/generate_samples.py loaded as a module (its RECEIPTS use dates relative to today)."""
    path = BACKEND_DIR / "scripts" / "generate_samples.py"
    spec = importlib.util.spec_from_file_location("era_generate_samples", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # keep scripts/ free of __pycache__
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer, built by the project's own sample generator."""
    with tempfile.TemporaryDirectory(prefix="era-pdf-") as tmp:
        path = Path(tmp) / "receipt.pdf"
        sample_generator().write_text_pdf(path, lines)
        return path.read_bytes()


def sample_pdf(name: str) -> bytes:
    """One of the demo receipts (e.g. "taj_hotel_invoice.pdf"), regenerated with fresh dates."""
    return text_pdf(sample_generator().RECEIPTS[name])


def upload(name: str, content: bytes | None = None, content_type: str | None = None) -> tuple[str, bytes, str | None]:
    """The (file_name, bytes, content_type) triple AgentService.add_receipts expects."""
    if content is None:
        content = sample_pdf(name)
    if content_type is None:
        content_type = "application/pdf" if name.endswith(".pdf") else None
    return name, content, content_type


def photo_bytes() -> bytes:
    return (SAMPLES_DIR / "chai_point_photo.png").read_bytes()


# --------------------------------------------------------------------- waiting


def wait_until(predicate: Callable[[], Any], timeout: float = 15.0, interval: float = 0.005,
               message: str = "condition") -> Any:
    """Poll ``predicate`` until it returns something truthy (only used where work runs on another thread)."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"Timed out after {timeout}s waiting for {message}")
        time.sleep(interval)


async def drain(*services: Any) -> None:
    """Await every background task spawned by AgentService / MockReimbursementGateway instances."""
    for _ in range(1000):
        pending = [task for service in services for task in list(service._tasks)]
        if not pending:
            return
        await asyncio.gather(*pending)
        await asyncio.sleep(0)  # let the done-callbacks remove finished tasks
    raise AssertionError("Background tasks did not settle")
