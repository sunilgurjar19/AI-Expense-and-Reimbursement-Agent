import asyncio
import logging
from dataclasses import dataclass, field

from app.core.config import LLMSection, ProviderName
from app.services.llm.base import LLMError, LLMProvider, LLMRequest, ProviderStatus
from app.services.llm.claude_provider import ClaudeProvider
from app.services.llm.mock_provider import MockProvider
from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    provider: str
    fell_back: bool
    errors: list[str] = field(default_factory=list)  # why earlier providers in the chain failed


class LLMRegistry:
    """Owns all providers, the active selection and the fallback chain."""

    def __init__(self, config: LLMSection) -> None:
        self._providers: dict[str, LLMProvider] = {
            "ollama": OllamaProvider(config.ollama, config.temperature),
            "claude": ClaudeProvider(config.claude),
            "mock": MockProvider(),
        }
        self._active: ProviderName = config.provider
        self._fallback_chain = config.fallback_chain
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    @property
    def active(self) -> ProviderName:
        return self._active

    def set_active(self, name: ProviderName) -> None:
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        self._active = name

    def statuses(self) -> list[ProviderStatus]:
        return [p.status() for p in self._providers.values()]

    async def health_check(self, name: str) -> ProviderStatus:
        return await self._providers[name].health_check()

    async def generate(self, request: LLMRequest) -> LLMResult:
        chain = [self._active, *(n for n in self._fallback_chain if n != self._active)]
        errors: list[str] = []
        async with self._semaphore:
            for index, name in enumerate(chain):
                try:
                    text = await self._providers[name].generate(request)
                    return LLMResult(text=text, provider=name, fell_back=index > 0, errors=errors)
                except LLMError as exc:
                    logger.warning("Provider %s failed for %s: %s", name, request.task, exc)
                    errors.append(f"{name}: {exc}")
        raise LLMError("; ".join(errors))
