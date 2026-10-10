"""Rule-based stand-in for an LLM.

Keeps the whole product usable offline: it reads the text layer of PDFs with
regular expressions and answers chat messages with simple intent matching.
"""

import json
import re

from app.services.llm.base import LLMProvider, LLMRequest, ProviderStatus
from app.services.rule_extractor import AMOUNT, extract_with_rules, find_date, to_float


class MockProvider(LLMProvider):
    name = "mock"
    label = "Offline rules engine"

    async def generate(self, request: LLMRequest) -> str:
        if request.task == "extract_receipt":
            return json.dumps(extract_with_rules(request.context.get("text", "")))
        if request.task == "verify_receipt":  # can't re-read an image; keep the draft
            return json.dumps(request.context.get("draft", {}))
        if request.task == "translate_fields":  # no translation offline; keep originals
            return "{}"
        if request.task == "infer_purpose":
            return json.dumps({"purpose": request.context.get("fallback")})
        return json.dumps(self._chat(request.context))

    # -------------------------------------------------------------- extraction

    # -------------------------------------------------------------------- chat

    def _chat(self, context: dict) -> dict:
        message: str = context.get("message", "").strip()
        lowered = message.lower()
        summary: dict = context.get("summary", {})
        pending: list[dict] = context.get("pending_questions", [])
        currency = summary.get("currency", "")

        if re.search(r"\b(total|how much|summary|status|overview)\b", lowered):
            reply = (
                f"Your claim **{summary.get('title')}** has {summary.get('receipt_count', 0)} expense(s) "
                f"totalling {currency} {summary.get('total_claimed', 0):,.2f}, of which "
                f"{currency} {summary.get('total_reimbursable', 0):,.2f} is reimbursable. "
                f"Readiness is {summary.get('readiness', 0)}%."
            )
            if pending:
                reply += f" I still need {len(pending)} answer(s) from you."
            return {"reply": reply, "answers": []}

        if re.search(r"\b(submit|ready)\b", lowered):
            if pending:
                return {"reply": f"Almost there - answer the {len(pending)} open question(s) and you can submit.", "answers": []}
            return {"reply": "Everything checks out. Hit **Submit claim** whenever you're ready.", "answers": []}

        if pending and message:
            question = pending[0]
            return {
                "reply": "Thanks, noted! " + ("Next one coming up." if len(pending) > 1 else "That was the last one."),
                "answers": [{"question_id": question["id"], "answer": self._coerce(question, message)}],
            }

        return {
            "reply": "Drop receipts (photos or PDFs) into the panel and I'll extract, categorise and check them. "
                     "You can ask me things like *what's my total?* or *is this ready to submit?*",
            "answers": [],
        }

    @staticmethod
    def _coerce(question: dict, message: str):
        if question.get("type") == "number":
            amounts = re.findall(AMOUNT, message)
            return to_float(amounts[0]) if amounts else message
        if question.get("type") == "date":
            return find_date(message) or message
        if question.get("type") in ("select", "choice"):
            for option in question.get("options", []):
                if option["label"].lower() in message.lower() or option["value"].lower() in message.lower():
                    return option["value"]
        return message

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            configured=True,
            healthy=True,
            detail="Always available · reads PDF text layers only",
            models={"vision": "regex-rules", "chat": "intent-rules"},
        )
