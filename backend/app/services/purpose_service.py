"""Works out what a claim's expenses were for, so the employee doesn't have to type it."""

import json
import logging
from datetime import date

from app.models.domain import Claim, ReceiptStage, User
from app.models.policy import TRAVEL_CATEGORIES, Policy
from app.services.llm import LLMError, LLMRegistry, LLMRequest
from app.services.normalizers import clean_str, parse_json_object

logger = logging.getLogger(__name__)

MAX_LENGTH = 200

SYSTEM_PROMPT = """You write the "purpose / remarks" line of an employee expense claim for their approver.
Base it only on the receipts provided. Be factual and specific: destination, dates and the kinds of spend.
Rules: never include any person's name; never invent clients, projects or meetings that the receipts don't show;
cover every kind of spend in the draft.
Respond with a single JSON object and nothing else."""

PROMPT_TEMPLATE = """Department: {department}
Receipts on this claim:
{receipts}

Draft built from the receipt categories:
"{draft}"

Improve the draft into one clear sentence (max 22 words). Keep the draft's dates and places exactly as written
and every kind of spend it lists; add a specific
reason only if a receipt clearly shows one (e.g. conference, training, client entertainment).
Return JSON: {{"purpose": string}}"""


class PurposeService:
    def __init__(self, registry: LLMRegistry, policy: Policy) -> None:
        self._registry = registry
        self._policy = policy

    async def infer(self, claim: Claim, employee: User | None) -> str | None:
        """Return a one-line purpose for the claim, or None if there's nothing to go on."""
        receipts = [
            r for r in claim.active_receipts
            if r.stage == ReceiptStage.COMPLETED and (r.data.vendor or r.data.category)
        ]
        if not receipts:
            return None

        fallback = self.summarise(claim)
        lines = [
            {
                "merchant": r.data.vendor,
                "category": self._label(r.data.category),
                "date": r.data.date,
                "city": r.data.location,
                "items": [i.description for i in r.data.line_items][:5],
            }
            for r in receipts
        ]
        request = LLMRequest(
            task="infer_purpose",
            system=SYSTEM_PROMPT,
            prompt=PROMPT_TEMPLATE.format(
                department=employee.department if employee else "",
                receipts=json.dumps(lines, default=str),
                draft=fallback or "",
            ),
            context={"fallback": fallback},
        )
        try:
            result = await self._registry.generate(request)
            purpose = clean_str(parse_json_object(result.text).get("purpose"))
        except LLMError:
            logger.warning("Purpose inference failed; using rule-based summary")
            purpose = None
        if purpose and employee and _mentions_person(purpose, employee):
            logger.info("Discarding inferred purpose that names the employee: %s", purpose)
            purpose = None
        return (purpose or fallback or "").strip(' "\'')[:MAX_LENGTH] or None

    def summarise(self, claim: Claim) -> str | None:
        """Deterministic purpose built from categories, cities and dates."""
        receipts = [r for r in claim.active_receipts if r.stage == ReceiptStage.COMPLETED]
        categories = [r.data.category for r in receipts if r.data.category]
        if not categories:
            return None

        labels = list(dict.fromkeys(self._label(c).lower() for c in categories))
        spend = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" and {labels[-1]}"
        period = self._period(claim)
        cities = [r.data.location.split(",")[-1].strip().title() for r in receipts if r.data.location]

        if TRAVEL_CATEGORIES & set(categories) and cities:
            city = max(set(cities), key=cities.count)
            return f"Business trip to {city}{f', {period}' if period else ''} - {spend}."
        return f"Business expenses{f' ({period})' if period else ''}: {spend}."

    def _label(self, key: str | None) -> str:
        rule = self._policy.category(key)
        return rule.label if rule else (key or "other").replace("_", " ")

    @staticmethod
    def _period(claim: Claim) -> str | None:
        if not claim.period_start:
            return None
        start = date.fromisoformat(claim.period_start)
        end = date.fromisoformat(claim.period_end or claim.period_start)
        if start == end:
            return f"{start.day} {start:%b %Y}"
        if (start.year, start.month) == (end.year, end.month):
            return f"{start.day}-{end.day} {end:%b %Y}"
        return f"{start.day} {start:%b} - {end.day} {end:%b %Y}"


def _mentions_person(text: str, employee: User) -> bool:
    lowered = text.lower()
    return any(len(part) > 2 and part.lower() in lowered for part in employee.name.split())
