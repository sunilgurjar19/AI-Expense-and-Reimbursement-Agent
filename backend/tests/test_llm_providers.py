"""LLM providers: the offline mock, Ollama (httpx.MockTransport) and Claude (fake SDK client). No network."""

import base64
import io
import json
from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import pytest
from PIL import Image

from app.core.config import ClaudeSection, OllamaSection
from app.services.llm import ImagePart, LLMError
from app.services.llm.claude_provider import SERVER_FALLBACK_BETA, ClaudeProvider
from app.services.llm.mock_provider import MockProvider
from app.services.llm.ollama_provider import MAX_IMAGES, ZOOM_NOTE, OllamaProvider, _zoomed_sections
from app.services.rule_extractor import extract_with_rules
from tests.helpers import llm_request


def jpeg(width: int, height: int) -> ImagePart:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buffer, format="JPEG")
    return ImagePart("image/jpeg", base64.b64encode(buffer.getvalue()).decode())


def image_size(part: ImagePart) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(part.data_b64))).size


# ======================================================================== mock


class TestMockProvider:
    async def test_extraction_uses_the_rules_engine_on_the_text_layer(self):
        text = "Starbucks Coffee\nDate: 02/10/2026\nTotal Rs. 490.00"
        raw = await MockProvider().generate(llm_request("extract_receipt", context={"text": text}))
        assert json.loads(raw) == extract_with_rules(text)

    @pytest.mark.parametrize(
        ("task", "context", "expected"),
        [
            ("verify_receipt", {"draft": {"fields": {"vendor": "Taj"}}}, {"fields": {"vendor": "Taj"}}),
            ("verify_receipt", {}, {}),
            ("translate_fields", {}, {}),
            ("infer_purpose", {"fallback": "Business trip to Pune."}, {"purpose": "Business trip to Pune."}),
        ],
    )
    async def test_tasks_it_cannot_really_do_are_answered_safely(self, task, context, expected):
        assert json.loads(await MockProvider().generate(llm_request(task, context=context))) == expected

    def test_status(self):
        status = MockProvider().status()
        assert (status.name, status.configured, status.healthy) == ("mock", True, True)
        assert status.models == {"vision": "regex-rules", "chat": "intent-rules"}


class TestMockChat:
    SUMMARY = {"title": "Pune trip", "currency": "INR", "receipt_count": 3, "total_claimed": 12500.5,
               "total_reimbursable": 9000, "readiness": 67}
    AMOUNT_Q = {"id": "q-amount", "type": "number", "kind": "confirm_amount", "options": []}
    CHOICE_Q = {"id": "q-dup", "type": "choice", "kind": "duplicate",
                "options": [{"value": "exclude", "label": "Remove it"}, {"value": "keep", "label": "It's a valid receipt"}]}

    async def chat(self, message: str, pending: list[dict] | None = None) -> dict:
        context = {"message": message, "summary": self.SUMMARY, "pending_questions": pending or []}
        return json.loads(await MockProvider().generate(llm_request("chat", context=context)))

    @pytest.mark.parametrize("message", ["What's my total?", "how much is reimbursable", "Give me a summary"])
    async def test_summary_intent_reports_the_totals(self, message):
        reply = await self.chat(message, pending=[self.AMOUNT_Q, self.CHOICE_Q])
        assert reply == {
            "reply": "Your claim **Pune trip** has 3 expense(s) totalling INR 12,500.50, of which INR 9,000.00 is "
                     "reimbursable. Readiness is 67%. I still need 2 answer(s) from you.",
            "answers": [],
        }

    @pytest.mark.parametrize(
        ("pending", "reply"),
        [
            ([AMOUNT_Q], "Almost there - answer the 1 open question(s) and you can submit."),
            ([], "Everything checks out. Hit **Submit claim** whenever you're ready."),
        ],
    )
    async def test_submit_intent(self, pending, reply):
        assert (await self.chat("Can I submit?", pending))["reply"] == reply

    async def test_free_text_answers_the_first_pending_question(self):
        reply = await self.chat("It was 1,250 rupees", pending=[self.AMOUNT_Q, self.CHOICE_Q])
        assert reply == {"reply": "Thanks, noted! Next one coming up.",
                         "answers": [{"question_id": "q-amount", "answer": 1250.0}]}
        assert (await self.chat("remove it", pending=[self.CHOICE_Q]))["reply"] == "Thanks, noted! That was the last one."

    @pytest.mark.parametrize("message", ["Hello there", ""])
    async def test_otherwise_it_explains_what_it_can_do(self, message):
        reply = await self.chat(message)
        assert reply["reply"].startswith("Drop receipts (photos or PDFs) into the panel") and reply["answers"] == []

    @pytest.mark.parametrize(
        ("question", "message", "expected"),
        [
            ({"type": "number"}, "it was 1,250.50", 1250.5),
            ({"type": "number"}, "no idea", "no idea"),
            ({"type": "date"}, "on 5 Oct 2026", "2026-10-05"),
            ({"type": "date"}, "last Tuesday", "last Tuesday"),
            (CHOICE_Q, "Please REMOVE IT", "exclude"),
            (CHOICE_Q, "keep", "keep"),
            ({"type": "select", "options": [{"value": "meals", "label": "🍽️ Meals"}]}, "groceries", "groceries"),
            ({"type": "text"}, "Client visit", "Client visit"),
        ],
    )
    def test_coerce(self, question, message, expected):
        assert MockProvider._coerce(question, message) == expected

    def test_coerce_reads_amounts_without_thousands_separators(self):
        assert MockProvider._coerce({"type": "number"}, "It was 1500") == 1500.0


# ====================================================================== ollama


class OllamaHarness:
    """An OllamaProvider whose HTTP client talks to an in-memory MockTransport."""

    def __init__(self, handler=None, **config):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda request: httpx.Response(200, json={"message": {"content": '{"ok": 1}'}}))
        self.provider = OllamaProvider(OllamaSection(**config), temperature=0.1)
        transport = httpx.MockTransport(self._handle)
        self.provider._client = lambda: httpx.AsyncClient(base_url=self.provider._config.base_url, transport=transport)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def payload(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


class TestOllamaGenerate:
    async def test_text_only_chat_request(self):
        harness = OllamaHarness(chat_model="llama3:8b", keep_alive="5m")
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        text = await harness.provider.generate(llm_request("chat", system="SYS", prompt="What's my total?",
                                                           history=history))
        assert text == '{"ok": 1}'
        request = harness.requests[0]
        assert (request.method, request.url.path) == ("POST", "/api/chat")
        assert harness.payload() == {
            "model": "llama3:8b",
            "messages": [{"role": "system", "content": "SYS"}, *history, {"role": "user", "content": "What's my total?"}],
            "stream": False,
            "keep_alive": "5m",
            "options": {"temperature": 0.1},
            "format": "json",
        }

    async def test_receipt_images_go_to_the_vision_model_with_zoomed_tiles(self):
        harness = OllamaHarness(vision_model="qwen2.5vl:7b")
        page = jpeg(100, 200)
        await harness.provider.generate(llm_request("extract_receipt", prompt="Extract", images=[page]))
        message = harness.payload()["messages"][-1]
        assert harness.payload()["model"] == "qwen2.5vl:7b"
        assert message["content"] == ZOOM_NOTE + "Extract"
        assert len(message["images"]) == 3 and message["images"][0] == page.data_b64

    @pytest.mark.parametrize(
        ("task", "context", "zoom_tiles"),
        [
            ("extract_receipt", {"zoom": False}, True),  # digital PDFs don't need zooming
            ("chat", {}, True),  # only extraction/verification tasks zoom
            ("verify_receipt", {"zoom": True}, False),  # disabled in config
        ],
    )
    async def test_zoom_is_skipped_when_not_useful(self, task, context, zoom_tiles):
        harness = OllamaHarness(zoom_tiles=zoom_tiles)
        await harness.provider.generate(llm_request(task, prompt="P", images=[jpeg(50, 50)], context=context))
        message = harness.payload()["messages"][-1]
        assert message["content"] == "P" and len(message["images"]) == 1

    async def test_number_of_images_is_capped(self):
        harness = OllamaHarness()
        await harness.provider.generate(llm_request("verify_receipt", images=[jpeg(40, 60) for _ in range(6)]))
        assert len(harness.payload()["messages"][-1]["images"]) == MAX_IMAGES

    async def test_free_text_mode_omits_the_json_format(self):
        harness = OllamaHarness()
        await harness.provider.generate(llm_request("chat", json_mode=False))
        assert "format" not in harness.payload()

    @pytest.mark.parametrize(
        ("handler", "message"),
        [
            (lambda r: httpx.Response(500, text="model crashed"), "Ollama request failed: HTTPStatusError"),
            (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), "Ollama request failed: ConnectError"),
            (lambda r: httpx.Response(200, json={"message": {"content": ""}}), "Ollama returned an empty response"),
            (lambda r: httpx.Response(200, json={}), "Ollama returned an empty response"),
        ],
        ids=["http-500", "unreachable", "empty-content", "no-message"],
    )
    async def test_failures_become_llm_errors(self, handler, message):
        harness = OllamaHarness(handler)
        with pytest.raises(LLMError, match=message):
            await harness.provider.generate(llm_request("chat"))


class TestOllamaStatus:
    def test_offline_status(self):
        status = OllamaProvider(OllamaSection(base_url="http://gpu-box:11434"), 0.1).status()
        assert (status.name, status.configured, status.healthy, status.detail) == (
            "ollama", True, None, "http://gpu-box:11434")
        assert status.models == {"vision": "gemma3:4b", "chat": "gemma3:4b"}

    async def test_healthy_when_every_configured_model_is_installed(self):
        tags = {"models": [{"name": "gemma3:4b"}, {"name": "llama3:8b"}]}
        harness = OllamaHarness(lambda r: httpx.Response(200, json=tags))
        status = await harness.provider.health_check()
        assert (status.healthy, status.detail) == (True, "Connected · 2 models installed")
        assert harness.requests[0].url.path == "/api/tags"

    async def test_missing_models_are_named(self):
        harness = OllamaHarness(lambda r: httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]}),
                                vision_model="qwen2.5vl:7b")
        status = await harness.provider.health_check()
        assert (status.healthy, status.detail) == (False, "Missing models: qwen2.5vl:7b - run `ollama pull <model>`")

    async def test_unreachable_server(self):
        def refuse(request):
            raise httpx.ConnectError("refused")

        status = await OllamaHarness(refuse, base_url="http://gpu-box:11434").provider.health_check()
        assert (status.healthy, status.detail) == (False, "Cannot reach Ollama at http://gpu-box:11434 (ConnectError)")

    async def test_real_client_uses_the_configured_url_and_timeout(self):
        provider = OllamaProvider(OllamaSection(base_url="http://gpu-box:11434", timeout_seconds=42), 0.1)
        async with provider._client() as client:
            assert (client.base_url.host, client.base_url.port) == ("gpu-box", 11434)
            assert client.timeout.read == 42


@pytest.mark.parametrize(
    ("size", "long_axis"),
    [((100, 200), 1), ((200, 100), 0)],
    ids=["portrait-top-and-bottom", "landscape-left-and-right"],
)
def test_zoomed_sections_are_two_overlapping_halves(size, long_axis):
    sections = _zoomed_sections(jpeg(*size))
    sizes = [image_size(s) for s in sections]
    short_axis = 1 - long_axis
    assert len(sizes) == 2 and all(s.media_type == "image/jpeg" for s in sections)
    assert all(s[short_axis] == size[short_axis] for s in sizes)  # each crop keeps the full short side
    assert all(abs(s[long_axis] - 0.58 * size[long_axis]) <= 1 for s in sizes)  # ~58% of the long side each
    assert sum(s[long_axis] for s in sizes) > size[long_axis]  # so the halves overlap in the middle


# ====================================================================== claude


def claude_message(*blocks: tuple[str, str], stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type=kind, text=text) for kind, text in blocks])


class FakeAnthropic:
    """Just enough of anthropic.AsyncAnthropic for ClaudeProvider."""

    def __init__(self, response=None, error: Exception | None = None, retrieve_error: Exception | None = None):
        self.calls: list[dict] = []
        self.retrieved: list[str] = []
        self._response, self._error, self._retrieve_error = response, error, retrieve_error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(retrieve=self._retrieve)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response

    async def _retrieve(self, model: str):
        self.retrieved.append(model)
        if self._retrieve_error:
            raise self._retrieve_error
        return SimpleNamespace(id=model)


def claude(fake: FakeAnthropic | None = None, **config) -> ClaudeProvider:
    provider = ClaudeProvider(ClaudeSection(api_key="sk-ant-test", **config))
    provider._client = fake  # replace the real SDK client: no request can leave the process
    return provider


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code: int, message: str):
    return cls(message, response=httpx2.Response(code, request=_REQUEST), body=None)


class TestClaudeConfiguration:
    async def test_without_a_key_it_is_not_configured(self):
        provider = ClaudeProvider(ClaudeSection())
        assert provider._client is None
        status = provider.status()
        assert (status.configured, status.detail) == (False, "Set ERA_LLM__CLAUDE__API_KEY")
        assert (await provider.health_check()).healthy is False
        with pytest.raises(LLMError, match="Claude API key is not configured"):
            await provider.generate(llm_request())

    def test_key_can_come_from_the_standard_environment_variable(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        status = ClaudeProvider(ClaudeSection()).status()
        assert (status.configured, status.detail) == (True, "API key configured")
        assert status.models == {"vision": "claude-opus-5-5", "chat": "claude-opus-5-5"}


class TestClaudeGenerate:
    async def test_extraction_request(self):
        fake = FakeAnthropic(claude_message(("thinking", "hmm"), ("text", '{"vendor":'), ("text", ' "Taj"}')))
        provider = claude(fake, vision_model="claude-vision", effort="high", max_tokens=1234)
        history = [{"role": "user", "content": "earlier"}]
        request = llm_request("extract_receipt", system="SYS", prompt="Extract", pdf_b64="JVBERi0=",
                              images=[ImagePart("image/jpeg", "aW1n")], history=history)

        assert await provider.generate(request) == '{"vendor": "Taj"}'
        (call,) = fake.calls
        assert call == {
            "model": "claude-vision",
            "max_tokens": 1234,
            "system": "SYS",
            "output_config": {"effort": "high"},
            "messages": [*history, {"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
                {"type": "text", "text": "Extract"},
            ]}],
            "betas": [SERVER_FALLBACK_BETA],
            "fallbacks": "default",
        }

    async def test_chat_uses_the_chat_model_and_effort_and_can_skip_server_fallbacks(self):
        fake = FakeAnthropic(claude_message(("text", "Hi!")))
        provider = claude(fake, chat_model="claude-chat", chat_effort="low", server_fallbacks=False)
        await provider.generate(llm_request("chat", prompt="hello"))
        (call,) = fake.calls
        assert (call["model"], call["output_config"]) == ("claude-chat", {"effort": "low"})
        assert "betas" not in call and "fallbacks" not in call
        assert call["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]

    async def test_images_are_sent_when_native_pdf_is_off(self):
        fake = FakeAnthropic(claude_message(("text", "{}")))
        images = [ImagePart("image/jpeg", "cGFnZTE="), ImagePart("image/png", "cGFnZTI=")]
        await claude(fake, native_pdf=False).generate(llm_request("verify_receipt", pdf_b64="JVBERi0=", images=images))
        content = fake.calls[0]["messages"][-1]["content"]
        assert [block["type"] for block in content] == ["image", "image", "text"]
        assert content[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "cGFnZTI="}

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (claude_message(("text", "I can't help with that"), stop_reason="refusal"), "Claude declined"),
            (claude_message(("thinking", "..."), ("tool_use", "")), "Claude returned an empty response"),
        ],
    )
    async def test_refusals_and_empty_answers_are_errors(self, response, message):
        with pytest.raises(LLMError, match=message):
            await claude(FakeAnthropic(response)).generate(llm_request())

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (status_error(anthropic.RateLimitError, 429, "slow down"), "Claude rate limit reached - try again shortly"),
            (status_error(anthropic.APIStatusError, 500, "overloaded"), "Claude API error 500: overloaded"),
            (anthropic.APIConnectionError(request=_REQUEST), "Cannot reach the Claude API"),
            (anthropic.APITimeoutError(request=_REQUEST), "Cannot reach the Claude API"),
        ],
        ids=["rate-limit", "status", "connection", "timeout"],
    )
    async def test_sdk_errors_become_llm_errors(self, error, message):
        with pytest.raises(LLMError, match=message):
            await claude(FakeAnthropic(error=error)).generate(llm_request())


class TestClaudeHealth:
    async def test_healthy_when_the_model_can_be_retrieved(self):
        fake = FakeAnthropic()
        status = await claude(fake, vision_model="claude-vision").health_check()
        assert (status.healthy, status.detail) == (True, "Connected to Anthropic API")
        assert fake.retrieved == ["claude-vision"]

    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            (status_error(anthropic.AuthenticationError, 401, "bad key"), "Claude API error 401"),
            (anthropic.APIConnectionError(request=_REQUEST), "Cannot reach the Claude API"),
        ],
    )
    async def test_unhealthy_on_api_or_connection_errors(self, error, detail):
        status = await claude(FakeAnthropic(retrieve_error=error)).health_check()
        assert (status.healthy, status.detail) == (False, detail)
