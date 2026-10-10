"""Core plumbing: layered settings, JWT access tokens and the in-process event bus."""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import BASE_DIR, Settings, get_settings
from app.core.events import EventBus
from app.core.security import TokenError, create_access_token, decode_access_token
from tests.helpers import BACKEND_DIR, REAL_STORAGE_DIR, make_settings

# ---------------------------------------------------------------------- settings


class TestSettings:
    def test_values_come_from_settings_yaml(self, tmp_path):
        settings = make_settings(tmp_path)
        assert (settings.app.agent_name, settings.app.company, settings.app.base_currency) == ("Rika", "Acme Corp", "INR")
        assert ".gif" in settings.storage.allowed_extensions  # only in the YAML, not in the code defaults
        assert settings.server.cors_origins == ["http://localhost:5200", "http://127.0.0.1:5200"]
        assert settings.llm.ollama.vision_model == "gemma3:4b"

    def test_environment_variables_override_the_yaml(self, monkeypatch):
        monkeypatch.setenv("ERA_APP__AGENT_NAME", "Zed")
        monkeypatch.setenv("ERA_PIPELINE__MAX_PDF_PAGES", "5")
        monkeypatch.setenv("ERA_LLM__CLAUDE__EFFORT", "high")
        settings = Settings(_env_file=None)
        assert (settings.app.agent_name, settings.pipeline.max_pdf_pages, settings.llm.claude.effort) == ("Zed", 5, "high")
        assert settings.app.company == "Acme Corp"  # untouched keys still come from the YAML

    def test_list_values_are_parsed_as_json(self, monkeypatch):
        monkeypatch.setenv("ERA_SERVER__CORS_ORIGINS", '["http://a.test", "http://b.test"]')
        monkeypatch.setenv("ERA_LLM__FALLBACK_CHAIN", '["claude", "mock"]')
        settings = Settings(_env_file=None)
        assert settings.server.cors_origins == ["http://a.test", "http://b.test"]
        assert settings.llm.fallback_chain == ["claude", "mock"]

    def test_constructor_arguments_beat_the_environment(self, monkeypatch):
        monkeypatch.setenv("ERA_APP__COMPANY", "Env Corp")
        settings = Settings(_env_file=None, app={"company": "Init Corp"})
        assert (settings.app.company, settings.app.agent_name) == ("Init Corp", "Rika")

    def test_dotenv_file_sits_between_the_environment_and_the_yaml(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("ERA_APP__COMPANY=DotEnv Corp\nERA_APP__AGENT_NAME=Dotty\n", encoding="utf-8")
        monkeypatch.setenv("ERA_APP__AGENT_NAME", "FromEnv")
        settings = Settings(_env_file=env_file)
        assert (settings.app.company, settings.app.agent_name) == ("DotEnv Corp", "FromEnv")

    def test_invalid_values_are_rejected(self, monkeypatch):
        monkeypatch.setenv("ERA_LLM__PROVIDER", "gpt")
        with pytest.raises(ValidationError, match="llm.provider"):
            Settings(_env_file=None)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("config/policy.yaml", BACKEND_DIR / "config" / "policy.yaml"),
         ("/tmp/elsewhere/db.json", Path("/tmp/elsewhere/db.json"))],
        ids=["relative", "absolute"],
    )
    def test_resolve_path_is_relative_to_the_backend_folder(self, tmp_path, value, expected):
        assert BASE_DIR == BACKEND_DIR
        assert make_settings(tmp_path).resolve_path(value) == expected

    def test_get_settings_is_cached(self):
        assert get_settings() is get_settings()


def test_the_test_session_is_isolated_from_real_data_and_services():
    """Guards the guard: the import-time container must not point at storage/, a real LLM or a real key."""
    from app.container import container

    settings = container.settings
    for configured in (settings.storage.database_file, settings.storage.upload_dir):
        path = settings.resolve_path(configured).resolve()
        assert REAL_STORAGE_DIR not in (path, *path.parents)  # REAL_STORAGE_DIR is built from the resolved backend dir
    assert (settings.llm.provider, settings.llm.fallback_chain) == ("mock", [])
    assert settings.llm.claude.api_key == "" and "ANTHROPIC_API_KEY" not in os.environ
    assert settings.pipeline.stage_delay_ms == 0 and settings.reimbursement.payout_delay_seconds == 0


@pytest.mark.parametrize(
    ("event", "args"),
    [
        ("open", ("{storage}/db.json", "r", 0)),
        ("os.listdir", ("{storage}",)),
        ("os.replace", ("/tmp/elsewhere.tmp", "{storage}/db.json", -1, -1)),
        ("shutil.rmtree", ("{storage}/uploads", None)),
    ],
)
def test_the_real_storage_folder_is_off_limits(event, args):
    """conftest installs an audit hook, so a stray path can't reach the live data. Synthetic audit events are
    raised here: the hook fires exactly as it would before real I/O, but no file is ever opened."""
    concrete = tuple(a.format(storage=REAL_STORAGE_DIR) if isinstance(a, str) else a for a in args)
    with pytest.raises(PermissionError, match="never touch the real storage folder"):
        sys.audit(event, *concrete)
    sys.audit(event, *(a.replace(str(REAL_STORAGE_DIR), str(REAL_STORAGE_DIR) + "-other") if isinstance(a, str)
                       else a for a in concrete))  # look-alike sibling paths are fine


# --------------------------------------------------------------------------- JWT


def secret() -> str:
    return get_settings().auth.jwt_secret


class TestAccessTokens:
    def test_round_trip(self):
        assert decode_access_token(create_access_token("u-1001")) == "u-1001"

    def test_expiry_follows_the_configured_ttl(self):
        payload = jwt.decode(create_access_token("u-1001"), secret(), algorithms=["HS256"])
        assert payload["exp"] - payload["iat"] == get_settings().auth.token_ttl_minutes * 60

    def test_expired_tokens_are_rejected(self, monkeypatch, tmp_path):
        expired = make_settings(tmp_path, auth={"token_ttl_minutes": -1})
        monkeypatch.setattr(security, "get_settings", lambda: expired)
        with pytest.raises(TokenError, match="expired"):
            decode_access_token(create_access_token("u-1001"))

    @pytest.mark.parametrize(
        "token",
        [
            jwt.encode({"sub": "u-1001"}, "another-secret-that-is-also-32-bytes-long", algorithm="HS256"),
            jwt.encode({"sub": "u-1001"}, None, algorithm="none"),  # unsigned tokens must not be accepted
            "not-a-jwt",
            "",
        ],
        ids=["wrong-secret", "alg-none", "garbage", "empty"],
    )
    def test_forged_or_malformed_tokens_are_rejected(self, token):
        with pytest.raises(TokenError):
            decode_access_token(token)

    @pytest.mark.parametrize("claims", [{}, {"sub": ""}], ids=["missing", "empty"])
    def test_tokens_without_a_subject_are_rejected(self, claims):
        exp = datetime.now(timezone.utc) + timedelta(minutes=5)
        token = jwt.encode({**claims, "exp": exp}, secret(), algorithm="HS256")
        with pytest.raises(TokenError, match="Token has no subject"):
            decode_access_token(token)


# --------------------------------------------------------------------- event bus


class TestEventBus:
    def test_published_events_reach_every_subscriber_of_that_user_only(self):
        bus = EventBus()
        first, second, other = bus.subscribe("u-1"), bus.subscribe("u-1"), bus.subscribe("u-2")

        bus.publish("u-1", "claim.updated", {"id": "clm-1"})

        expected = {"type": "claim.updated", "data": {"id": "clm-1"}}
        assert first.get_nowait() == expected and second.get_nowait() == expected
        assert other.empty()

    def test_unsubscribing_the_last_queue_forgets_the_user(self):
        bus = EventBus()
        first, second = bus.subscribe("u-1"), bus.subscribe("u-1")
        bus.unsubscribe("u-1", first)
        assert bus._subscribers["u-1"] == {second}
        bus.unsubscribe("u-1", second)
        bus.unsubscribe("u-1", second)  # idempotent
        assert "u-1" not in bus._subscribers

    def test_publishing_without_subscribers_is_a_no_op(self):
        bus = EventBus()
        bus.publish("u-404", "notification", {"x": 1})
        assert dict(bus._subscribers) == {}

    def test_slow_subscribers_drop_events_instead_of_blocking(self, caplog):
        bus = EventBus()
        queue = bus.subscribe("u-1")
        for number in range(queue.maxsize):
            bus.publish("u-1", "notification", {"n": number})
        with caplog.at_level(logging.WARNING, logger="app.core.events"):
            bus.publish("u-1", "notification", {"n": "overflow"})
        assert queue.qsize() == 500
        assert "Dropping event notification for slow subscriber u-1" in caplog.text

    async def test_a_waiting_subscriber_is_woken_by_publish(self):
        bus = EventBus()
        queue = bus.subscribe("u-1")
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        bus.publish("u-1", "claim.updated", {"id": "clm-1"})
        assert await asyncio.wait_for(waiter, timeout=1) == {"type": "claim.updated", "data": {"id": "clm-1"}}
