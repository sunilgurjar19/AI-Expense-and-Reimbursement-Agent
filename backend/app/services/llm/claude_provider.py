import os

import anthropic

from app.core.config import ClaudeSection
from app.services.llm.base import LLMError, LLMProvider, LLMRequest, ProviderStatus

SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider(LLMProvider):
    name = "claude"
    label = "Claude (Anthropic)"

    def __init__(self, config: ClaudeSection) -> None:
        self._config = config
        api_key = config.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = (
            anthropic.AsyncAnthropic(api_key=api_key, timeout=config.timeout_seconds)
            if api_key
            else None
        )

    async def generate(self, request: LLMRequest) -> str:
        if self._client is None:
            raise LLMError("Claude API key is not configured")

        is_extraction = request.task in ("extract_receipt", "verify_receipt")
        model = self._config.vision_model if is_extraction else self._config.chat_model
        effort = self._config.effort if is_extraction else self._config.chat_effort

        extra: dict = {}
        if self._config.server_fallbacks:
            extra = {"betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}

        try:
            message = await self._client.beta.messages.create(
                model=model,
                max_tokens=self._config.max_tokens,
                system=request.system,
                output_config={"effort": effort},
                messages=[*request.history, {"role": "user", "content": self._content(request)}],
                **extra,
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude rate limit reached - try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Cannot reach the Claude API") from exc

        if message.stop_reason == "refusal":
            raise LLMError("Claude declined to process this request")

        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise LLMError("Claude returned an empty response")
        return text

    def _content(self, request: LLMRequest) -> list[dict]:
        content: list[dict] = []
        if request.pdf_b64 and self._config.native_pdf:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": request.pdf_b64,
                    },
                }
            )
        else:
            content.extend(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.media_type, "data": img.data_b64},
                }
                for img in request.images
            )
        content.append({"type": "text", "text": request.prompt})
        return content

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            configured=self._client is not None,
            detail="API key configured" if self._client else "Set ERA_LLM__CLAUDE__API_KEY",
            models={"vision": self._config.vision_model, "chat": self._config.chat_model},
        )

    async def health_check(self) -> ProviderStatus:
        status = self.status()
        if self._client is None:
            status.healthy = False
            return status
        try:
            await self._client.models.retrieve(self._config.vision_model)
        except anthropic.APIStatusError as exc:
            status.healthy = False
            status.detail = f"Claude API error {exc.status_code}"
            return status
        except anthropic.APIConnectionError:
            status.healthy = False
            status.detail = "Cannot reach the Claude API"
            return status
        status.healthy = True
        status.detail = "Connected to Anthropic API"
        return status
