from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


class LLMError(Exception):
    """Raised when a provider cannot produce a completion."""


@dataclass(frozen=True)
class ImagePart:
    media_type: str  # image/png, image/jpeg ...
    data_b64: str


@dataclass
class LLMRequest:
    """Provider-agnostic completion request.

    ``task`` and ``context`` let rule-based providers (the mock) work from
    structured inputs, while real models rely on ``system`` + ``prompt``.
    """

    task: Literal["extract_receipt", "verify_receipt", "translate_fields", "chat", "infer_purpose"]
    system: str
    prompt: str
    images: list[ImagePart] = field(default_factory=list)
    pdf_b64: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    json_mode: bool = True
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    name: str
    label: str
    configured: bool
    healthy: bool | None = None
    detail: str = ""
    models: dict[str, str] = field(default_factory=dict)


class LLMProvider(ABC):
    name: str
    label: str

    @abstractmethod
    async def generate(self, request: LLMRequest) -> str:
        """Return the raw text completion."""

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Cheap, offline description of the provider configuration."""

    async def health_check(self) -> ProviderStatus:
        """Live connectivity check. Defaults to the offline status."""
        return self.status()
