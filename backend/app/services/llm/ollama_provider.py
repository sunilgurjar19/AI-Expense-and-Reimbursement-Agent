import base64
import io

import httpx
from PIL import Image

from app.core.config import OllamaSection
from app.services.llm.base import ImagePart, LLMError, LLMProvider, LLMRequest, ProviderStatus

MAX_IMAGES = 6
ZOOM_NOTE = (
    "Image 1 is the whole document. The following images are zoomed-in, overlapping sections of the same "
    "document (top to bottom) - use them to read small or handwritten text.\n\n"
)


def _zoomed_sections(image: ImagePart) -> list[ImagePart]:
    """Two overlapping halves of a page, so small vision models see handwriting at a readable size."""
    page = Image.open(io.BytesIO(base64.b64decode(image.data_b64))).convert("RGB")
    width, height = page.size
    if height >= width:
        boxes = [(0, 0, width, int(height * 0.58)), (0, int(height * 0.42), width, height)]
    else:
        boxes = [(0, 0, int(width * 0.58), height), (int(width * 0.42), 0, width, height)]
    sections = []
    for box in boxes:
        buffer = io.BytesIO()
        page.crop(box).save(buffer, format="JPEG", quality=90)
        sections.append(ImagePart("image/jpeg", base64.b64encode(buffer.getvalue()).decode()))
    return sections


class OllamaProvider(LLMProvider):
    name = "ollama"
    label = "Ollama (local)"

    def __init__(self, config: OllamaSection, temperature: float) -> None:
        self._config = config
        self._temperature = temperature

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.base_url, timeout=self._config.timeout_seconds
        )

    async def generate(self, request: LLMRequest) -> str:
        has_media = bool(request.images)
        model = self._config.vision_model if has_media else self._config.chat_model

        prompt, images = request.prompt, list(request.images)
        zoom = request.context.get("zoom", True) and request.task in ("extract_receipt", "verify_receipt")
        if has_media and self._config.zoom_tiles and zoom:
            images = [images[0], *_zoomed_sections(images[0]), *images[1:]][:MAX_IMAGES]
            prompt = ZOOM_NOTE + prompt

        user_message: dict = {"role": "user", "content": prompt}
        if has_media:
            user_message["images"] = [img.data_b64 for img in images]

        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system},
                *request.history,
                user_message,
            ],
            "stream": False,
            "keep_alive": self._config.keep_alive,
            "options": {"temperature": self._temperature},
        }
        if request.json_mode:
            payload["format"] = "json"

        try:
            async with self._client() as client:
                response = await client.post("/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc!r}") from exc

        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise LLMError("Ollama returned an empty response")
        return content

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            label=self.label,
            configured=True,
            detail=self._config.base_url,
            models={"vision": self._config.vision_model, "chat": self._config.chat_model},
        )

    async def health_check(self) -> ProviderStatus:
        status = self.status()
        try:
            async with self._client() as client:
                response = await client.get("/api/tags", timeout=5)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            status.healthy = False
            status.detail = f"Cannot reach Ollama at {self._config.base_url} ({exc.__class__.__name__})"
            return status

        installed = {m["name"] for m in response.json().get("models", [])}
        missing = [m for m in set(status.models.values()) if m not in installed]
        status.healthy = not missing
        status.detail = (
            f"Missing models: {', '.join(missing)} - run `ollama pull <model>`"
            if missing
            else f"Connected · {len(installed)} models installed"
        )
        return status
