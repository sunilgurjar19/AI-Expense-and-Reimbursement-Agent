"""Turns a messy document into structured expense data.

Pipeline (driven by AgentService so each step is visible in the UI):
  1. extract()  - multilingual, layout-aware extraction by the LLM, gaps filled from the PDF text layer
  2. review()   - deterministic checks (arithmetic, dates, scripts, totals)
  3. verify()   - if checks fail, the model re-reads the document with its draft and the issues
  4. finalise() - remaining issues lower field confidence, so the agent asks the user to confirm
"""

import json
from dataclasses import dataclass, field
from typing import Literal

from app.models.domain import ExpenseData, LineItem
from app.models.policy import Policy
from app.services.document_reader import DocumentContent
from app.services.extraction_checks import Issue, amounts_close, find_issues
from app.services.llm import LLMError, LLMRegistry, LLMRequest
from app.services.normalizers import (
    clean_str,
    has_non_latin_letters,
    normalise_currency,
    normalise_date,
    normalise_reference,
    parse_json_object,
    to_amount,
)
from app.services.rule_extractor import extract_with_rules

EXTRACTION_FIELDS = [
    "vendor", "date", "total_amount", "currency", "tax_amount", "category",
    "payment_method", "invoice_number", "location", "description",
]

GAP_FILL_FIELDS = ["vendor", "date", "total_amount", "currency", "tax_amount", "invoice_number", "location"]

UNRESOLVED_CONFIDENCE = 0.5  # below the low-confidence threshold, so the agent asks to confirm

SYSTEM_PROMPT = """You are an expert accounts-payable assistant who reads receipts, bills and invoices from India
and around the world - printed or handwritten, photographed or scanned, in any language or script.
Extract only facts that are visible on the document. Never invent values: use null when something is not shown.
Respond with a single JSON object and nothing else."""

RULES = """Reading rules:
- Documents may be in Hindi, Marathi, Gujarati, Tamil, Telugu, Kannada, Bengali, English or a mix. Read them in the
  original language, but write every output value in ENGLISH: transliterate names
  (e.g. "मनिष सर्विस सेंटर" -> "Manish Service Center") and translate item descriptions (e.g. "डीझेल" -> "Diesel").
  Put the merchant name exactly as printed, in its original script, in "vendor_local", and the language in "language".
- The merchant (vendor) is the business that issued the bill - the shop / dealer / outlet name, usually the
  largest text - not the brand or franchise it sells (e.g. an Indian Oil dealer: use the dealer's name).
- Dates on Indian bills are DAY first (dd/mm/yy, dd-mm-yyyy). "ता." / "दिनांक" / "Dt." mean date.
  Copy the date exactly as written into "date_as_printed" (e.g. "20/09/26"), and also give "date" as YYYY-MM-DD.
- "एकूण" / "कुल" / "योग" / "Total" / "Net Amount" / "Grand Total" mark the total. "रु." / "Rs." / "₹" = rupees;
  "पै." is a paise column - combine it with the rupees column.
- Bill / memo / invoice numbers ("कॅश मेमो नं.", "Bill No", "Invoice No") go in invoice_number with no spaces.
  A GSTIN (15 characters, e.g. 27AABFM8546L1ZT) is NOT an invoice number.
- Tables: read row by row. A handwritten value belongs to the row it is written on; rows with no values are not
  line items. For each line item give quantity, unit_price (rate) and amount; quantity x unit_price ~= amount.
- Handwritten digits: read each digit carefully (4 vs 9, 1 vs 7, 0 vs 6). Cross-check the row amount, the total
  and quantity x rate - they must agree.
- location = the city or area from the merchant's address (e.g. "Navi Mumbai"), not the seller/brand line.
- Cash memos are paid in cash unless stated otherwise.
- Fuel bills (petrol, diesel, CNG): diesel is for cars; use the two-wheeler category only if the bill says so."""

SHAPE = """{{
  "is_receipt": true | false,
  "language": string | null,
  "fields": {{
    "vendor": string | null,
    "vendor_local": string | null,
    "date_as_printed": string | null,
    "date": "YYYY-MM-DD" | null,
    "total_amount": number | null,
    "currency": "ISO 4217 code" | null,
    "tax_amount": number | null,
    "category": one of the category keys below | null,
    "payment_method": string | null,
    "invoice_number": string | null,
    "address_as_printed": string | null,
    "location": string | null,
    "description": string | null
  }},
  "confidence": {{ "<field>": 0.0-1.0 }},
  "line_items": [{{ "description": string, "quantity": number | null, "unit_price": number | null, "amount": number | null }}],
  "notes": string | null
}}"""

EXTRACT_PROMPT = """Extract the expense from this document.

{rules}

Return JSON with exactly this shape:
{shape}
"description" is a short English summary of what was bought (max 12 words).
"notes" mentions anything unusual (handwritten, faded, cut off, several receipts on one page).

Category keys (key = meaning):
{categories}

The company's default currency is {base_currency}. File name: "{file_name}".
{text_block}"""

VERIFY_PROMPT = """A first reading of this document produced the draft below, but automatic checks found problems.
Look at the document again, very carefully, and return a corrected version.

Problems to fix:
{issues}

{rules}

Draft:
{draft}

Return the corrected JSON in exactly this shape:
{shape}

Category keys (key = meaning):
{categories}
{text_block}"""

TRANSLATE_PROMPT = """These values were read from a {language} receipt. Translate them to short, natural English.
For "address", return only the city / area (e.g. "Mahape, Navi Mumbai").
Keep numbers, codes and brand names unchanged.

{values}

Return JSON with the same keys, values in English."""

VerifyMode = Literal["auto", "always", "off"]


def _unreadable_message(fell_back: bool, errors: list[str]) -> str:
    """Explain why a photo/scan came back empty, and what to do about it."""
    if fell_back:
        reason = errors[0].split(":", 1)[-1].strip()[:140] if errors else "it did not respond"
        return (f"The AI engine couldn't read this photo/scan ({reason}), and the offline engine only reads "
                "PDFs with a text layer. Check that the AI engine is running, then click Re-read.")
    return ("The offline rules engine is active - it can only read PDFs with a text layer, not photos or scans. "
            "Switch the AI engine to Ollama or Claude in Settings, then click Re-read.")


def _reconcile_line_items(items: list[LineItem], total: float | None) -> None:
    """Fix a common misreading: "Item x 2   64.00" where 64.00 is the row total, read as the unit rate."""
    if total is None or not items or any(i.unit_price is None for i in items):
        return
    if amounts_close(sum(i.amount or 0 for i in items), total):
        return
    if amounts_close(sum(i.unit_price for i in items), total):  # type: ignore[misc]
        for item in items:
            item.amount = item.unit_price
            item.unit_price = round(item.amount / item.quantity, 2) if item.quantity and item.amount else None


def _looks_like_city(value: str | None) -> bool:
    """A plausible English city/area name, not a whole address or seller line."""
    return bool(value) and len(value) <= 40 and not has_non_latin_letters(value) and not any(
        ch.isdigit() or ch == ":" for ch in value
    )


@dataclass
class ExtractionResult:
    data: ExpenseData
    confidence: dict[str, float] = field(default_factory=dict)
    is_receipt: bool = True
    notes: str | None = None
    source: str = "unknown"
    fell_back: bool = False
    verified: bool = False
    issues: list[Issue] = field(default_factory=list)
    address_local: str | None = None  # address as printed, used to derive an English city
    read_warning: str | None = None


class ExtractionService:
    def __init__(
        self, registry: LLMRegistry, policy: Policy, base_currency: str, verify_mode: VerifyMode = "auto"
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._base_currency = base_currency
        self._verify_mode = verify_mode

    # --------------------------------------------------------------- passes

    async def extract(self, document: DocumentContent, file_name: str) -> ExtractionResult:
        request = self._request(
            "extract_receipt",
            EXTRACT_PROMPT.format(
                rules=RULES,
                shape=SHAPE,
                categories=self._categories(),
                base_currency=self._base_currency,
                file_name=file_name,
                text_block=self._text_block(document),
            ),
            document,
            context={"text": document.text, "file_name": file_name},
        )
        result = await self._registry.generate(request)
        extraction = self._normalise(parse_json_object(result.text), result.provider, result.fell_back)
        if document.text and result.provider != "mock":
            self._fill_gaps_from_text(extraction, document.text)
        if result.provider == "mock" and not document.text:
            extraction.read_warning = _unreadable_message(result.fell_back, result.errors)
        return extraction

    def review(self, extraction: ExtractionResult) -> list[Issue]:
        return find_issues(extraction.data)

    def should_verify(self, extraction: ExtractionResult, issues: list[Issue], document: DocumentContent) -> bool:
        if self._verify_mode == "off" or extraction.source == "mock":
            return False
        if not (document.images or document.pdf_b64 or document.text):
            return False
        non_english = (extraction.data.language or "english").strip().lower() not in ("english", "en")
        return self._verify_mode == "always" or bool(issues) or non_english or bool(extraction.data.vendor_local)

    async def verify(
        self, document: DocumentContent, file_name: str, draft: ExtractionResult, issues: list[Issue]
    ) -> ExtractionResult:
        """Second look at the document. Keeps whichever reading passes more checks."""
        problems = "\n".join(f"- {i.message}" for i in issues) or (
            "- No arithmetic problems found, but this is a non-English or handwritten document: re-check which "
            "table row each handwritten value is written on (e.g. Petrol vs Diesel), every digit, the date and the city."
        )
        request = self._request(
            "verify_receipt",
            VERIFY_PROMPT.format(
                issues=problems,
                rules=RULES,
                draft=json.dumps(self._as_payload(draft), ensure_ascii=False, indent=1),
                shape=SHAPE,
                categories=self._categories(),
                text_block=self._text_block(document),
            ),
            document,
            context={"draft": self._as_payload(draft)},
        )
        try:
            result = await self._registry.generate(request)
        except LLMError:
            return draft
        if result.provider == "mock":  # the rules engine can't re-read an image
            return draft

        checked = self._normalise(parse_json_object(result.text), result.provider, result.fell_back)
        self._keep_missing(checked, draft)
        if document.text:
            self._fill_gaps_from_text(checked, document.text)
        checked.verified = True
        return checked if len(self.review(checked)) <= len(issues) else draft

    async def localise(self, extraction: ExtractionResult) -> ExtractionResult:
        """Translate leftover non-English values (line items, description, city) with a cheap text-only call."""
        data = extraction.data
        values: dict[str, str] = {}
        for index, item in enumerate(data.line_items):
            if has_non_latin_letters(item.description):
                values[f"item_{index}"] = item.description
        if has_non_latin_letters(data.description):
            values["description"] = data.description  # type: ignore[assignment]
        address = extraction.address_local or data.location
        if address and not _looks_like_city(data.location):
            values["address"] = address
        if not values:
            return extraction

        request = LLMRequest(
            task="translate_fields",
            system="You translate receipt text from Indian and other languages into English.",
            prompt=TRANSLATE_PROMPT.format(
                language=data.language or "non-English",
                values=json.dumps(values, ensure_ascii=False, indent=1),
            ),
        )
        try:
            translated = parse_json_object((await self._registry.generate(request)).text)
        except LLMError:
            return extraction

        for key, value in translated.items():
            english = clean_str(value)
            if not english or has_non_latin_letters(english):
                continue
            if key.startswith("item_") and key[5:].isdigit() and int(key[5:]) < len(data.line_items):
                data.line_items[int(key[5:])].description = english
            elif key == "description":
                data.description = english
            elif key == "address" and _looks_like_city(english):
                data.location = english
        return extraction

    def finalise(self, extraction: ExtractionResult) -> ExtractionResult:
        """Record unresolved issues and lower confidence on the affected fields."""
        extraction.issues = self.review(extraction)
        for issue in extraction.issues:
            if getattr(extraction.data, issue.field, None) is not None:
                extraction.confidence[issue.field] = min(
                    extraction.confidence.get(issue.field, 1.0), UNRESOLVED_CONFIDENCE
                )
        notes = [extraction.notes] if extraction.notes else []
        if extraction.verified:
            notes.append("Double-checked by a second reading.")
        if extraction.issues:
            notes.append("Please confirm: " + " ".join(i.message.split(" - ")[0] for i in extraction.issues[:2]))
        extraction.notes = " ".join(notes) or None
        return extraction

    # -------------------------------------------------------------- helpers

    def _request(self, task: str, prompt: str, document: DocumentContent, context: dict) -> LLMRequest:
        # Zoomed crops only help photos and scans; digital PDFs already have a readable text layer.
        return LLMRequest(
            task=task,  # type: ignore[arg-type]
            system=SYSTEM_PROMPT,
            prompt=prompt,
            images=document.images,
            pdf_b64=document.pdf_b64,
            context={**context, "zoom": not document.text},
        )

    def _categories(self) -> str:
        return "\n".join(f'- "{c.key}" = {c.label}' for c in self._policy.categories)

    @staticmethod
    def _text_block(document: DocumentContent) -> str:
        if not document.text:
            return ""
        return f"\nText layer extracted from the PDF (may be incomplete):\n<<<\n{document.text[:6000]}\n>>>"

    def _fill_gaps_from_text(self, extraction: ExtractionResult, text: str) -> None:
        """Small models sometimes skip fields that are plainly printed; recover them from the text layer."""
        rules = self._normalise(extract_with_rules(text), source="rules", fell_back=False)
        filled = []
        for name in GAP_FILL_FIELDS:
            if getattr(extraction.data, name) is None and getattr(rules.data, name) is not None:
                setattr(extraction.data, name, getattr(rules.data, name))
                extraction.confidence[name] = min(rules.confidence.get(name, 0.7), 0.7)
                filled.append(name)
        if not extraction.data.line_items:
            extraction.data.line_items = rules.data.line_items
        if filled:
            extraction.is_receipt = extraction.is_receipt or rules.is_receipt
            note = f"Filled {', '.join(filled)} from the PDF text."
            extraction.notes = f"{extraction.notes} {note}" if extraction.notes else note

    @staticmethod
    def _keep_missing(checked: ExtractionResult, draft: ExtractionResult) -> None:
        """A verification pass should not lose fields the first pass did find."""
        for name in [*EXTRACTION_FIELDS, "vendor_local", "language"]:
            if getattr(checked.data, name) is None and getattr(draft.data, name) is not None:
                setattr(checked.data, name, getattr(draft.data, name))
                if name in draft.confidence:
                    checked.confidence[name] = draft.confidence[name]
        checked.address_local = checked.address_local or draft.address_local

    @staticmethod
    def _as_payload(extraction: ExtractionResult) -> dict:
        data = extraction.data.model_dump(exclude={"business_purpose", "attendees", "line_items"})
        return {
            "is_receipt": extraction.is_receipt,
            "language": data.pop("language"),
            "fields": data,
            "line_items": [i.model_dump() for i in extraction.data.line_items],
            "notes": extraction.notes,
        }

    # ------------------------------------------------------------ normalise

    def _normalise(self, payload: dict, source: str, fell_back: bool) -> ExtractionResult:
        # Models don't always follow the shape: fall back to top-level keys / default confidence.
        fields = payload.get("fields")
        if not isinstance(fields, dict) or not fields:
            fields = {k: payload.get(k) for k in EXTRACTION_FIELDS}
        raw_conf = payload.get("confidence")
        if not isinstance(raw_conf, dict):
            raw_conf = {}

        line_items = []
        for item in payload.get("line_items") or []:
            if not isinstance(item, dict) or not clean_str(item.get("description")):
                continue
            quantity, unit_price = to_amount(item.get("quantity")), to_amount(item.get("unit_price"))
            amount = to_amount(item.get("amount"))
            if amount is None and quantity and unit_price:
                amount = round(quantity * unit_price, 2)
            if amount is None and quantity is None and unit_price is None:
                continue  # an empty table row
            line_items.append(LineItem(
                description=str(item["description"]).strip(), quantity=quantity, unit_price=unit_price, amount=amount
            ))

        data = ExpenseData(
            vendor=clean_str(fields.get("vendor")),
            vendor_local=clean_str(fields.get("vendor_local")),
            language=clean_str(payload.get("language") or fields.get("language")),
            date=self._pick_date(fields),
            total_amount=to_amount(fields.get("total_amount")),
            currency=normalise_currency(fields.get("currency")),
            tax_amount=to_amount(fields.get("tax_amount")),
            category=self._normalise_category(fields.get("category")),
            payment_method=clean_str(fields.get("payment_method")),
            invoice_number=normalise_reference(fields.get("invoice_number")),
            location=clean_str(fields.get("location")),
            description=clean_str(fields.get("description")),
            line_items=line_items,
        )
        _reconcile_line_items(line_items, data.total_amount)
        if data.total_amount is None and line_items and all(i.amount is not None for i in line_items):
            data.total_amount = round(sum(i.amount for i in line_items), 2)  # type: ignore[misc]
        if data.total_amount is not None and data.currency is None:
            data.currency = self._base_currency
        if data.vendor_local and data.vendor_local == data.vendor:
            data.vendor_local = None

        confidence = {}
        for name in EXTRACTION_FIELDS:
            if getattr(data, name) is None:
                continue
            try:
                confidence[name] = max(0.0, min(1.0, float(raw_conf.get(name, 0.8))))
            except (TypeError, ValueError):
                confidence[name] = 0.8

        return ExtractionResult(
            data=data,
            confidence=confidence,
            is_receipt=bool(payload.get("is_receipt", True)),
            notes=clean_str(payload.get("notes")),
            source=source,
            fell_back=fell_back,
            address_local=clean_str(fields.get("address_as_printed")),
        )

    @staticmethod
    def _pick_date(fields: dict) -> str | None:
        """Prefer our own day-first parse of the date as printed; models often mis-convert dd/mm/yy."""
        return normalise_date(fields.get("date_as_printed")) or normalise_date(fields.get("date"))

    def _normalise_category(self, value) -> str | None:
        text = clean_str(value)
        if not text:
            return None
        lowered = text.lower().replace(" ", "_")
        for rule in self._policy.categories:
            if lowered in (rule.key, rule.label.lower().replace(" ", "_")):
                return rule.key
        return None
