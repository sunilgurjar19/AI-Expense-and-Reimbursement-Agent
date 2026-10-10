"""LLMRegistry: active provider, fallback chain, error reporting and the concurrency limit."""

import asyncio

import pytest

from app.core.config import LLMSection
from app.services.llm import LLMError, LLMRegistry
from tests.helpers import ConcurrencyProbe, FakeProvider, llm_request


def make_registry(active="ollama", chain=("mock",), concurrency=2, **providers) -> LLMRegistry:
    registry = LLMRegistry(LLMSection(provider=active, fallback_chain=list(chain), max_concurrency=concurrency))
    registry._providers.update(providers)
    return registry


async def test_the_active_provider_answers_first():
    ollama, mock = FakeProvider("ollama", reply='{"from": "ollama"}'), FakeProvider("mock")
    result = await make_registry(ollama=ollama, mock=mock).generate(llm_request())
    assert (result.text, result.provider, result.fell_back, result.errors) == ('{"from": "ollama"}', "ollama", False, [])
    assert mock.calls == []


async def test_failures_fall_back_along_the_chain_and_are_reported():
    registry = make_registry(
        active="claude",
        chain=("ollama", "mock"),
        claude=FakeProvider("claude", error="API key missing"),
        ollama=FakeProvider("ollama", error="connection refused"),
        mock=FakeProvider("mock", reply="{}"),
    )
    result = await registry.generate(llm_request("extract_receipt"))
    assert (result.provider, result.fell_back) == ("mock", True)
    assert result.errors == ["claude: API key missing", "ollama: connection refused"]


async def test_the_active_provider_is_not_retried_from_the_chain():
    mock = FakeProvider("mock", error="boom")
    with pytest.raises(LLMError, match="^mock: boom$"):
        await make_registry(active="mock", chain=("mock",), mock=mock).generate(llm_request())
    assert len(mock.calls) == 1


async def test_when_every_provider_fails_all_reasons_are_raised():
    registry = make_registry(active="claude", chain=("ollama",), claude=FakeProvider("claude", error="a"),
                             ollama=FakeProvider("ollama", error="b"))
    with pytest.raises(LLMError, match="^claude: a; ollama: b$"):
        await registry.generate(llm_request())


async def test_unexpected_exceptions_are_not_mistaken_for_provider_failures():
    registry = make_registry(ollama=FakeProvider("ollama", raises=KeyError("bug")), mock=FakeProvider("mock"))
    with pytest.raises(KeyError):
        await registry.generate(llm_request())


def test_switching_the_active_provider():
    registry = make_registry()
    registry.set_active("claude")
    assert registry.active == "claude"
    with pytest.raises(ValueError, match="Unknown provider: gpt"):
        registry.set_active("gpt")  # type: ignore[arg-type]
    assert registry.active == "claude"


async def test_statuses_and_health_checks_of_the_real_providers():
    registry = make_registry()
    statuses = {s.name: s for s in registry.statuses()}
    assert list(statuses) == ["ollama", "claude", "mock"]
    assert statuses["claude"].configured is False  # no API key in the test environment
    assert statuses["mock"].healthy is True

    assert (await registry.health_check("mock")).healthy is True
    assert (await registry.health_check("claude")).healthy is False  # answered offline, no API call


@pytest.mark.parametrize(("limit", "expected_peak"), [(2, 2), (0, 1)])
async def test_concurrent_calls_are_limited(limit, expected_peak):
    probe = ConcurrencyProbe()
    registry = make_registry(concurrency=limit, ollama=FakeProvider("ollama", delay=0.01, probe=probe))
    results = await asyncio.gather(*(registry.generate(llm_request()) for _ in range(6)))
    assert len(results) == 6
    assert probe.peak == expected_peak
