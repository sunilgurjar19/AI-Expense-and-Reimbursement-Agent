"""The reimbursement agent: orchestrates the pipeline and talks to the user."""

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.models.domain import (
    ChatMessage,
    Claim,
    ClaimStatus,
    Question,
    Receipt,
    ReceiptStage,
    TimelineEvent,
    User,
)
from app.repositories.claim_repository import ClaimRepository
from app.repositories.user_repository import UserRepository
from app.services.chat_guard import ChatGuard
from app.services.claim_service import AnswerError, ClaimService
from app.services.document_reader import DocumentReader
from app.services.extraction_service import ExtractionService
from app.services.llm import LLMError, LLMRegistry, LLMRequest
from app.services.normalizers import parse_json_object
from app.services.notification_service import NotificationService
from app.services.policy_engine import PolicyEngine
from app.services.purpose_service import PurposeService

logger = logging.getLogger(__name__)

STAGE_PROGRESS = {
    ReceiptStage.READING: 12,
    ReceiptStage.EXTRACTING: 30,
    ReceiptStage.VERIFYING: 55,
    ReceiptStage.CATEGORISING: 72,
    ReceiptStage.VALIDATING: 85,
    ReceiptStage.DUPLICATE_CHECK: 95,
    ReceiptStage.COMPLETED: 100,
}

CHAT_SYSTEM_PROMPT = """You are {agent}, a friendly, concise expense & reimbursement assistant at {company}.
You help an employee turn receipts into a submission-ready claim.
Rules:
- Be brief (1-3 sentences), warm and specific. Use the claim data provided; never invent receipts or amounts.
- Take every amount from "Claim state" and "Receipts": earlier messages may quote totals that are out of date.
- Only return "answers", "updates" or "claim_purpose" for facts the employee states in their latest message.
  A question from the employee is never an answer, and never copy a pending question's text as an answer.
- If the user's message answers one of the pending questions, return it in "answers" with that question's id.
  Example: a justification is pending and the employee explains why the hotel cost more ->
  {{"answers": [{{"question_id": "<id of that question>", "answer": "<their explanation>"}}]}}.
- Never say you added, noted or changed something unless you return it in "answers", "updates" or "claim_purpose".
- If the user asks to correct a receipt field, return it in "updates" (fields: vendor, date (YYYY-MM-DD),
  total_amount, currency, category, business_purpose, attendees, description).
- If the user states the overall purpose of the trip/expenses, set "claim_purpose".
Reply ONLY with JSON: {{"reply": str, "answers": [{{"question_id": str, "answer": any}}],
"updates": [{{"receipt_id": str, "field": str, "value": any}}], "claim_purpose": str | null}}"""


# A reply that says the agent changed something (checked when nothing was actually applied).
_CLAIMS_A_CHANGE = re.compile(r"\b(?:add|not|updat|sav|record|chang|remov|mark)(?:ed|ing)\b|\bmade a note\b", re.I)


class UploadError(ValueError):
    """An uploaded file was rejected."""


class ClaimLockedError(Exception):
    """The claim was submitted and can no longer be changed."""


class AgentService:
    def __init__(
        self,
        settings: Settings,
        claims: ClaimRepository,
        reader: DocumentReader,
        extractor: ExtractionService,
        engine: PolicyEngine,
        claim_service: ClaimService,
        notifications: NotificationService,
        registry: LLMRegistry,
        purpose: PurposeService,
        users: UserRepository,
        publish: Callable[[Claim], None],
    ) -> None:
        self._settings = settings
        self._claims = claims
        self._reader = reader
        self._extractor = extractor
        self._engine = engine
        self._claim_service = claim_service
        self._notifications = notifications
        self._registry = registry
        self._purpose = purpose
        self._users = users
        self._publish = publish
        self._guard = ChatGuard(engine.policy)
        self._upload_dir = settings.resolve_path(settings.storage.upload_dir)
        self._stage_delay = settings.pipeline.stage_delay_ms / 1000
        self._tasks: set[asyncio.Task] = set()

    @property
    def _currency(self) -> str:
        return self._settings.app.base_currency

    # ----------------------------------------------------------------- claims

    def create_claim(self, user: User, title: str | None, purpose: str | None) -> Claim:
        first_name = user.name.split()[0]
        claim = Claim(
            user_id=user.id,
            currency=self._currency,
            title=title or "New expense claim",
            title_is_auto=not title,
        )
        self._claim_service.set_purpose(claim, purpose)
        claim.timeline.append(TimelineEvent(status="draft", label="Claim created", actor=user.name))
        claim.messages.append(
            ChatMessage(
                role="agent",
                text=f"Hi {first_name}! 👋 I'm {self._settings.app.agent_name}. Drop your bills here - photos, "
                     f"screenshots or PDFs - and I'll read them, sort them into categories, check them "
                     f"against policy and get your claim ready to submit.",
            )
        )
        self._claim_service.recompute(claim)
        return self._claims.save(claim)

    def claim_dir(self, claim: Claim) -> Path:
        return self._upload_dir / claim.user_id / claim.id

    def receipt_path(self, claim: Claim, receipt: Receipt) -> Path:
        return self.claim_dir(claim) / receipt.stored_name

    def delete_claim(self, claim: Claim) -> None:
        """Remove an unsubmitted claim and its uploaded files."""
        self._ensure_editable(claim)
        self._claims.delete(claim.id)
        shutil.rmtree(self.claim_dir(claim), ignore_errors=True)

    # ---------------------------------------------------------------- uploads

    def add_receipts(self, claim: Claim, files: list[tuple[str, bytes, str | None]]) -> list[Receipt]:
        """Store uploaded files and start processing them in the background."""
        self._ensure_editable(claim)
        storage = self._settings.storage
        max_bytes = storage.max_upload_mb * 1024 * 1024

        receipts: list[Receipt] = []
        for file_name, content, content_type in files:
            suffix = Path(file_name).suffix.lower()
            if suffix not in storage.allowed_extensions:
                raise UploadError(f"{file_name}: unsupported file type ({suffix or 'none'})")
            if len(content) > max_bytes:
                raise UploadError(f"{file_name}: larger than {storage.max_upload_mb} MB")
            if not content:
                raise UploadError(f"{file_name}: file is empty")

            receipt = Receipt(
                claim_id=claim.id,
                file_name=file_name,
                stored_name=f"{uuid4().hex}{suffix}",
                mime_type=content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
            path = self.receipt_path(claim, receipt)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            receipts.append(receipt)

        claim.receipts.extend(receipts)
        count = len(receipts)
        self._say(claim, f"Got {count} file{'s' if count > 1 else ''}! 📥 Reading "
                         f"{'them' if count > 1 else 'it'} now - you can watch each step on the right.")
        self._claim_service.recompute(claim)
        self._save(claim)
        self._spawn(self._process_batch(claim.id, [r.id for r in receipts]))
        return receipts

    def resume_interrupted(self) -> None:
        """Re-queue receipts that were mid-pipeline when the server stopped."""
        for claim in self._claims.all():
            pending = [
                r.id for r in claim.receipts
                if claim.is_editable and r.stage not in (ReceiptStage.COMPLETED, ReceiptStage.FAILED)
            ]
            if pending:
                self._spawn(self._process_batch(claim.id, pending))

    def retry_receipt(self, claim: Claim, receipt: Receipt) -> None:
        self._ensure_editable(claim)
        receipt.stage, receipt.progress, receipt.error = ReceiptStage.UPLOADED, 0, None
        self._claim_service.recompute(claim)
        self._save(claim)
        self._spawn(self._process_batch(claim.id, [receipt.id]))

    async def _process_batch(self, claim_id: str, receipt_ids: list[str]) -> None:
        claim = self._claims.get(claim_id)
        status_before = claim.status if claim else None
        await asyncio.gather(*(self._process_receipt(claim_id, rid) for rid in receipt_ids))

        claim = self._claims.get(claim_id)
        if claim is None:
            return
        await self._infer_purpose(claim)
        claim = self._claims.get(claim_id)
        if claim is None:
            return
        self._claim_service.recompute(claim)
        processed = [r for r in claim.receipts if r.id in receipt_ids]
        self._say(claim, self._batch_summary(claim, processed), meta={"kind": "summary"})
        self._save(claim)

        failed = sum(r.stage == ReceiptStage.FAILED for r in processed)
        level = "warning" if failed or claim.questions else "success"
        self._notifications.notify(
            claim.user_id,
            "Receipts processed",
            f"{len(processed) - failed} of {len(processed)} receipt(s) read for “{claim.title}”"
            + (f" · {len(claim.questions)} question(s) waiting" if claim.questions else ""),
            level=level,
            link=f"/agent/{claim.id}",
        )
        self._announce_ready(claim, status_before)

    async def _process_receipt(self, claim_id: str, receipt_id: str) -> None:
        try:
            await self._advance(claim_id, receipt_id, ReceiptStage.READING)
            claim, receipt = self._lookup(claim_id, receipt_id)
            document = await asyncio.to_thread(
                self._reader.read, self.receipt_path(claim, receipt), receipt.mime_type
            )

            await self._advance(claim_id, receipt_id, ReceiptStage.EXTRACTING)
            claim, receipt = self._lookup(claim_id, receipt_id)
            result = await self._extractor.extract(document, receipt.file_name)

            # Sanity-check the reading; re-read the document if something doesn't add up.
            await self._advance(claim_id, receipt_id, ReceiptStage.VERIFYING)
            claim, receipt = self._lookup(claim_id, receipt_id)
            issues = self._extractor.review(result)
            if self._extractor.should_verify(result, issues, document):
                result = await self._extractor.verify(document, receipt.file_name, result, issues)
            result = self._extractor.finalise(await self._extractor.localise(result))

            claim, receipt = self._lookup(claim_id, receipt_id)
            receipt.data = result.data
            receipt.confidence = result.confidence
            receipt.is_receipt = result.is_receipt
            receipt.extraction_notes = result.notes
            receipt.extraction_source = result.source
            receipt.read_warning = result.read_warning
            await self._advance(claim_id, receipt_id, ReceiptStage.CATEGORISING)

            claim, receipt = self._lookup(claim_id, receipt_id)
            receipt.data.category = self._engine.categorise(receipt, document.text)
            await self._advance(claim_id, receipt_id, ReceiptStage.VALIDATING)

            claim, receipt = self._lookup(claim_id, receipt_id)
            self._engine.evaluate(receipt)
            await self._advance(claim_id, receipt_id, ReceiptStage.DUPLICATE_CHECK)

            # Duplicate detection runs in ClaimService.recompute once the receipt is completed.
            await self._advance(claim_id, receipt_id, ReceiptStage.COMPLETED, delay=False)
        except _ReceiptGone:
            logger.info("Receipt %s removed while processing", receipt_id)
        except (LLMError, OSError, ValueError) as exc:
            logger.exception("Failed to process receipt %s", receipt_id)
            self._fail(claim_id, receipt_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - one bad file must not break the batch
            logger.exception("Unexpected error processing receipt %s", receipt_id)
            self._fail(claim_id, receipt_id, f"Unexpected error: {exc.__class__.__name__}")

    async def _advance(self, claim_id: str, receipt_id: str, stage: ReceiptStage, delay: bool = True) -> None:
        claim, receipt = self._lookup(claim_id, receipt_id)
        receipt.stage = stage
        receipt.progress = STAGE_PROGRESS[stage]
        self._claim_service.recompute(claim)
        self._save(claim)
        if delay and self._stage_delay:
            await asyncio.sleep(self._stage_delay)

    def _fail(self, claim_id: str, receipt_id: str, error: str) -> None:
        try:
            claim, receipt = self._lookup(claim_id, receipt_id)
        except _ReceiptGone:
            return
        receipt.stage, receipt.progress, receipt.error = ReceiptStage.FAILED, 100, error[:300]
        self._claim_service.recompute(claim)
        self._save(claim)

    def _lookup(self, claim_id: str, receipt_id: str) -> tuple[Claim, Receipt]:
        claim = self._claims.get(claim_id)
        receipt = claim.receipt(receipt_id) if claim else None
        if claim is None or receipt is None or not claim.is_editable:
            raise _ReceiptGone()
        return claim, receipt

    async def _infer_purpose(self, claim: Claim) -> None:
        """Fill in (or refresh) the claim's purpose unless the employee wrote it themselves."""
        if claim.purpose_source == "user" or not claim.is_editable:
            return
        claim.purpose_inferring = True
        self._claim_service.recompute(claim)
        self._save(claim)
        try:
            purpose = await self._purpose.infer(claim, self._users.get(claim.user_id))
        finally:
            claim.purpose_inferring = False
            current = self._claims.get(claim.id)
            if current is not None:
                current.purpose_inferring = False
        if current is None:
            return  # deleted while the model was thinking: don't bring it back
        if purpose and current.is_editable and current.purpose_source != "user":
            self._claim_service.set_purpose(current, purpose, source="agent")
        self._claim_service.recompute(current)
        self._save(current)

    def _batch_summary(self, claim: Claim, processed: list[Receipt]) -> str:
        ok = [r for r in processed if r.stage == ReceiptStage.COMPLETED and not r.excluded]
        failed = [r for r in processed if r.stage == ReceiptStage.FAILED]
        unreadable = [r for r in processed if r.read_warning and not r.excluded]
        parts: list[str] = []
        if ok:
            lines = []
            for r in ok:
                rule = self._engine.policy.category(r.data.category)
                amount = f"{self._currency} {r.amount_in_base:,.2f}" if r.amount_in_base is not None else "amount unknown"
                lines.append(f"{rule.icon if rule else '🧾'} {r.data.vendor or r.file_name} - {amount}")
            parts.append("Done reading! Here's what I found:\n" + "\n".join(lines))
        if failed:
            parts.append(f"⚠️ I couldn't read {len(failed)} file(s). You can retry or fill the details in manually.")
        if unreadable:
            parts.append(f"⚠️ I couldn't read the text on {len(unreadable)} photo/scan(s). {unreadable[0].read_warning}")
        parts.append(
            f"Claim total so far: **{self._currency} {claim.total_claimed:,.2f}** "
            f"(reimbursable {self._currency} {claim.total_reimbursable:,.2f})."
        )
        if claim.purpose and claim.purpose_source == "agent":
            parts.append(f"📝 I've added the remarks: “{claim.purpose}” - edit them in **Remarks** if that's not right.")
        if claim.questions:
            n = len(claim.questions)
            parts.append(f"I just need {n} quick answer{'s' if n > 1 else ''} from you 👇")
        elif claim.status == ClaimStatus.READY:
            parts.append("Everything checks out - your claim is **ready to submit** ✅")
        return "\n\n".join(parts)

    # ---------------------------------------------------------------- answers

    def answer_question(self, claim: Claim, question_id: str, answer) -> Claim:
        self._ensure_editable(claim)
        question = next((q for q in claim.questions if q.id == question_id), None)
        if question is None:
            raise AnswerError("This question was already answered")

        status_before = claim.status
        echo = self._claim_service.apply_answer(claim, question, answer)
        claim.messages.append(ChatMessage(role="user", text=echo, meta={"question_id": question_id}))
        self._claim_service.recompute(claim)
        self._say(claim, self._next_step_message(claim))
        self._save(claim)
        self._announce_ready(claim, status_before)
        return claim

    def _next_step_message(self, claim: Claim) -> str:
        if claim.status == ClaimStatus.READY:
            return (f"Perfect, that's everything! 🎉 Your claim for **{self._currency} "
                    f"{claim.total_reimbursable:,.2f}** is ready to submit.")
        if claim.questions:
            remaining = len(claim.questions)
            return f"Got it 👍 {remaining} more to go." if remaining > 1 else "Got it 👍 Just one more."
        if claim.status == ClaimStatus.PROCESSING:
            return "Got it 👍 I'm still reading the remaining receipts."
        return "Got it 👍 Please review the highlighted items before submitting."

    # ------------------------------------------------------------------- chat

    async def chat(self, claim: Claim, user: User, message: str) -> Claim:
        claim.messages.append(ChatMessage(role="user", text=message))
        self._save(claim)
        status_before = claim.status

        context = self._chat_context(claim, message)
        request = LLMRequest(
            task="chat",
            system=CHAT_SYSTEM_PROMPT.format(agent=self._settings.app.agent_name, company=self._settings.app.company),
            # The live claim state goes last, next to the message, so small models prefer it over old replies.
            prompt=(
                f"Recent conversation (amounts in it may be out of date):\n{context['transcript']}\n\n"
                f"Employee: {user.name}\nClaim state:\n{json.dumps(context['summary'], default=str)}\n"
                f"Receipts:\n{json.dumps(context['receipts'], default=str)}\n"
                f"Pending questions:\n{json.dumps(context['pending_questions'])}\n\n"
                f"User message: {message}"
            ),
            context=context,
        )

        provider = None
        try:
            result = await self._registry.generate(request)
            provider = result.provider
            payload = parse_json_object(result.text)
        except LLMError:
            logger.exception("Chat generation failed")
            payload = {"reply": "Sorry, I'm having trouble thinking right now - please try again in a moment."}

        current = self._claims.get(claim.id)
        if current is None:
            return claim  # deleted while the model was replying: don't bring it back
        claim = current
        applied = self._apply_chat_actions(claim, payload, message) if claim.is_editable else 0
        if applied:
            self._claim_service.recompute(claim)

        reply = str(payload.get("reply") or "").strip() or self._next_step_message(claim)
        if not applied and _CLAIMS_A_CHANGE.search(reply):  # keep the agent honest about what it did
            reply += "\n\n_(Nothing was changed: answer with the question cards, or edit the receipt.)_"
        self._say(claim, reply, meta={"provider": provider, "applied": applied})
        self._save(claim)
        self._announce_ready(claim, status_before)
        return claim

    def _chat_context(self, claim: Claim, message: str) -> dict:
        return {
            "message": message,
            "summary": {
                "title": claim.title,
                "status": claim.status,
                "purpose": claim.purpose,
                "currency": self._currency,
                "receipt_count": len(claim.active_receipts),
                "total_claimed": claim.total_claimed,
                "total_reimbursable": claim.total_reimbursable,
                "readiness": claim.readiness,
                "checklist": [i.model_dump() for i in claim.checklist],
            },
            "receipts": [
                {
                    "id": r.id,
                    "file": r.file_name,
                    "status": r.status,
                    **r.data.model_dump(exclude={"line_items"}),
                    "flags": [f.message for f in r.flags],
                }
                for r in claim.active_receipts
            ],
            "pending_questions": [
                q.model_dump(include={"id", "kind", "prompt", "type", "options"}) for q in claim.questions
            ],
            # Batch summaries quote totals that go stale, so the model only sees the live numbers above.
            "transcript": "\n".join(
                f"{m.role}: {m.text[:300]}" for m in claim.messages[-8:] if m.meta.get("kind") != "summary"
            ),
        }

    def _apply_chat_actions(self, claim: Claim, payload: dict, message: str) -> int:
        """Apply the model's structured actions, keeping only those grounded in the employee's message."""
        applied = 0
        questions = {q.id: q for q in claim.questions}
        garbled: list[Question] = []  # questions the model targeted with a value the employee didn't state
        for item in _objects(payload.get("answers")):
            question = questions.get(str(item.get("question_id")))
            if question is None:
                continue
            if not self._guard.answer(question, item.get("answer"), message):
                logger.info("Ignoring chat answer to %s (not stated in the message): %.120r",
                            question.kind, item.get("answer"))
                garbled.append(question)
                continue
            try:
                self._claim_service.apply_answer(claim, question, item.get("answer"))
                applied += 1
            except AnswerError as exc:
                logger.info("Ignoring chat answer: %s", exc)

        # Small models often pick the right question but copy its wording instead of the employee's: for a
        # narrative answer (justification, purpose) the employee's own statement is the answer.
        if not applied and len(garbled) == 1 and self._guard.own_words_answer(garbled[0], message):
            self._claim_service.apply_answer(claim, garbled[0], message)
            applied += 1

        for item in _objects(payload.get("updates")):
            receipt = claim.receipt(str(item.get("receipt_id")))
            field = str(item.get("field"))
            if receipt is None:
                continue
            if not self._guard.update(field, item.get("value"), message):
                logger.info("Ignoring chat update of %s (not stated in the message): %.120r", field, item.get("value"))
                continue
            try:
                self._claim_service.set_field(receipt, field, item.get("value"))
                applied += 1
            except AnswerError as exc:
                logger.info("Ignoring chat update: %s", exc)

        purpose = payload.get("claim_purpose")
        if (
            isinstance(purpose, str) and purpose.strip() and claim.purpose_source != "user"
            and self._guard.purpose(purpose, message, claim.purpose)
        ):
            self._claim_service.set_purpose(claim, purpose)
            applied += 1
        return applied

    # ---------------------------------------------------------------- helpers

    def _announce_ready(self, claim: Claim, status_before: ClaimStatus | None) -> None:
        if claim.status == ClaimStatus.READY and status_before != ClaimStatus.READY:
            self._notifications.notify(
                claim.user_id, "Ready to submit ✨",
                f"“{claim.title}” passed every check. Review and submit when you're ready.",
                level="success", link=f"/agent/{claim.id}",
            )

    def _say(self, claim: Claim, text: str, meta: dict | None = None) -> None:
        claim.messages.append(ChatMessage(role="agent", text=text, meta=meta or {}))

    def _save(self, claim: Claim) -> None:
        self._claims.save(claim)
        self._publish(claim)

    def save(self, claim: Claim) -> None:
        """Recompute, persist and broadcast a claim changed outside the agent."""
        self._claim_service.recompute(claim)
        self._save(claim)

    @staticmethod
    def _ensure_editable(claim: Claim) -> None:
        if not claim.is_editable:
            raise ClaimLockedError("This claim has been submitted and can no longer be changed")

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


class _ReceiptGone(Exception):
    """The claim or receipt was deleted/locked while processing."""


def _objects(value) -> list[dict]:
    """The dict entries of a model-supplied list; anything else (strings, a lone object...) is ignored."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
