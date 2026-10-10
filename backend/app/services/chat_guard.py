"""Checks that actions proposed by the chat model come from what the employee actually wrote.

Small local models sometimes "answer" a pending question from an unrelated message (even by echoing the
question back), or overwrite the claim's remarks with something said in passing. Before the agent applies
an answer, a field update or new remarks from the model, the value must be grounded in the employee's
latest message.
"""

import re
from datetime import date

from app.models.domain import Question
from app.models.policy import Policy
from app.services.normalizers import ascii_digits, clean_str, normalise_currency, normalise_date, to_amount
from app.services.rule_extractor import find_date

NARRATIVE_KINDS = {"justification", "purpose", "business_purpose"}  # a whole sentence is a fine answer
TEXT_OVERLAP = 0.6  # share of a value's words that must appear in the message
ECHO_OVERLAP = 0.75  # share of an answer's words taken from the question itself that makes it an echo

_WORD = re.compile(r"[^\W_]+")  # letters and digits, any script
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_STOPWORDS = frozenset(
    "a an and are as at be been but by for from had has have i in is it its me my of on or our so that the "
    "their them there this to was we were what with you your".split()
)
_AFFIRMATIVE = re.compile(
    r"^\s*(yes|yeah|yep|yup|correct|right|ok|okay|sure|confirm(ed)?|exactly|that'?s (right|correct)|looks (right|good))\b",
    re.I,
)
_PURPOSE_CUE = re.compile(r"\b(purpose|remarks?|reason for|w(?:as|ere) for)\b", re.I)
_CHOICE_CUES = {  # choice values used by the question engine -> words that ask for them
    "exclude": {"remove", "delete", "drop", "exclude", "discard"},
    "keep": {"keep", "both", "different", "valid", "genuine", "retain"},
}
_GENERIC_LABEL_WORDS = {"reimbursement", "expenses", "expense", "allowance", "other"}  # in many category labels
_CURRENCY_WORDS = {
    "INR": ("₹", "rs", "rupee"), "USD": ("$", "dollar"), "EUR": ("€", "euro"), "GBP": ("£", "pound"),
    "AED": ("dirham", "dhs"), "SGD": ("s$", "singapore"), "JPY": ("¥", "yen"),
}


class ChatGuard:
    def __init__(self, policy: Policy) -> None:
        self._policy = policy

    def answer(self, question: Question, value, message: str) -> bool:
        """May the model's `value` be used as the employee's answer to `question`?"""
        if question.type == "choice":
            return _choice_requested(question, value, message)
        if question.kind in ("category", "currency"):
            return self.update(question.kind, value, message)
        if question.kind == "confirm_amount" and _AFFIRMATIVE.match(message):
            return _same_amount(value, question.default) or _amount_in(value, message)
        if is_question(message):  # the employee is asking something, not answering
            return False
        if question.type == "number":
            return _amount_in(value, message)
        if question.type == "date":
            return _date_in(value, message)
        return _text_in(value, message) and not _echoes(value, question.prompt)

    def update(self, field: str, value, message: str) -> bool:
        """May the model change a receipt `field` to `value`? ("Can you change X to Y?" is fine.)"""
        if field in ("total_amount", "tax_amount"):
            return _amount_in(value, message)
        if field == "date":
            return _date_in(value, message)
        if field == "currency":
            return _currency_in(value, message)
        if field == "category":
            return self._category_mentioned(clean_str(value), message)
        return _text_in(value, message)

    def _category_mentioned(self, key: str | None, message: str) -> bool:
        rule = self._policy.category(key)
        if rule is None:
            return False
        names = [w for w in _content_words(f"{rule.key.replace('_', ' ')} {rule.label}") if w not in _GENERIC_LABEL_WORDS]
        said = _content_words(message)
        return any(_same_word(w, s) for w in names for s in said) or any(
            re.search(rf"\b{re.escape(k.lower())}\b", message.lower()) if k.isascii() else k in message
            for k in rule.keywords
        )

    def own_words_answer(self, question: Question, message: str) -> bool:
        """When the model picked the right narrative question but garbled the value, may the employee's
        message itself be the answer? Only a substantive statement that doesn't just restate the question."""
        return (
            question.kind in NARRATIVE_KINDS and not is_question(message)
            and len(_content_words(message)) >= 4 and not _echoes(message, question.prompt)
        )

    def purpose(self, text, message: str, current: str | None) -> bool:
        """New remarks must be stated; existing remarks are only replaced when the employee asks for it."""
        if not _text_in(text, message):
            return False
        if _PURPOSE_CUE.search(message):
            return True
        return not current and not is_question(message)


# ---------------------------------------------------------------- helpers


def is_question(message: str) -> bool:
    return message.strip().endswith("?")


def _squash(text: str) -> str:
    return " ".join(text.lower().replace("*", "").split())


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS]


def _same_word(a: str, b: str) -> bool:
    """Equal, or one is a prefix of the other ("meal" / "meals", "visit" / "visited")."""
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def _words_in(text: str, message: str) -> bool:
    words, said = _content_words(text), _content_words(message)
    if not words:
        return False
    return sum(1 for w in words if any(_same_word(w, s) for s in said)) / len(words) >= TEXT_OVERLAP


def _text_in(value, message: str) -> bool:
    text = clean_str(value)
    if not text:
        return False
    return _squash(text) in _squash(message) or _words_in(text, message)


def _echoes(value, prompt: str) -> bool:
    """Mostly the question's own words: the model restated the question instead of answering it.
    Examples in brackets ("(e.g. client visit to Pune)") are not part of the question."""
    words, asked = _content_words(str(value)), _content_words(re.sub(r"\([^)]*\)", " ", prompt))
    if len(words) < 3:
        return False
    return sum(1 for w in words if any(_same_word(w, a) for a in asked)) / len(words) >= ECHO_OVERLAP


def _numbers(message: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(ascii_digits(message)) if n.strip(",")]


def _same_amount(a, b) -> bool:
    a, b = to_amount(a), to_amount(b)
    return a is not None and b is not None and abs(a - b) < 0.005


def _amount_in(value, message: str) -> bool:
    amount = to_amount(value)
    return amount is not None and any(abs(amount - n) < 0.005 for n in _numbers(message))


def _date_in(value, message: str) -> bool:
    target = normalise_date(value)
    if not target:
        return False
    if find_date(ascii_digits(message)) == target:
        return True
    day, text = date.fromisoformat(target), ascii_digits(message).lower()
    has_day = re.search(rf"\b0?{day.day}(?:st|nd|rd|th)?\b", text)
    has_month = re.search(rf"\b{day:%b}".lower(), text) or re.search(rf"[/.-]0?{day.month}\b", text)
    return bool(has_day and has_month)


def _currency_in(value, message: str) -> bool:
    code = normalise_currency(value)
    if not code:
        return False
    text = message.lower()
    return bool(re.search(rf"\b{code.lower()}\b", text)) or any(w in text for w in _CURRENCY_WORDS.get(code, ()))


def _choice_requested(question: Question, value, message: str) -> bool:
    """A choice ("Remove duplicate" / "Keep both") needs a word that asks for that option."""
    if not any(o["value"] == value for o in question.options):
        return False
    return bool(_CHOICE_CUES.get(value, set()) & set(_content_words(message)))
