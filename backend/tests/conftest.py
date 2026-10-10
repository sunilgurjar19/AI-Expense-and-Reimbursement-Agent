"""Shared fixtures.

Isolation happens at import time, *before* anything from ``app`` is imported: ``app.container`` builds a
global ``Container(get_settings())`` on import, and it must never see the real ``storage/`` folder, a real
LLM provider or a real API key.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="era-tests-"))
atexit.register(shutil.rmtree, _SESSION_DIR, ignore_errors=True)

TEST_ENV = {
    "ERA_STORAGE__DATABASE_FILE": str(_SESSION_DIR / "global" / "db.json"),
    "ERA_STORAGE__UPLOAD_DIR": str(_SESSION_DIR / "global" / "uploads"),
    "ERA_LLM__PROVIDER": "mock",
    "ERA_LLM__FALLBACK_CHAIN": "[]",
    "ERA_LLM__CLAUDE__API_KEY": "",
    "ERA_LLM__OLLAMA__BASE_URL": "http://ollama.test:11434",
    "ERA_PIPELINE__STAGE_DELAY_MS": "0",
    "ERA_REIMBURSEMENT__PAYOUT_DELAY_SECONDS": "0",
    "ERA_AUTH__JWT_SECRET": "unit-test-secret-long-enough-for-hs256-signing",
}
for _key in [k for k in os.environ if k.startswith("ERA_") and k not in TEST_ENV]:
    del os.environ[_key]  # stray shell overrides must not change test behaviour
os.environ.update(TEST_ENV)
os.environ.pop("ANTHROPIC_API_KEY", None)

# backend/storage/ holds the developer's live database and uploads. Beyond pointing the settings elsewhere,
# refuse *any* file-system access below it for the whole test process (audit hooks cannot be bypassed).
_REAL_STORAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
_GUARDED_EVENTS = {"open", "os.remove", "os.rename", "os.replace", "os.mkdir", "os.rmdir", "os.listdir",
                   "os.scandir", "os.truncate", "os.chmod", "os.utime", "shutil.rmtree", "shutil.copyfile"}


def _guard_real_storage(event: str, args: tuple) -> None:
    if event not in _GUARDED_EVENTS:
        return
    for arg in args[:2]:
        if isinstance(arg, (str, bytes, os.PathLike)):
            path = os.path.abspath(os.fsdecode(arg))
            if path == _REAL_STORAGE or path.startswith(_REAL_STORAGE + os.sep):
                raise PermissionError(f"Tests must never touch the real storage folder ({event}: {path})")


sys.addaudithook(_guard_real_storage)

# --- everything below may import the application -------------------------------------------------

from collections.abc import Callable, Iterator  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import httpx2  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.container import Container  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.events import EventBus  # noqa: E402
from app.models.policy import Policy  # noqa: E402
from app.repositories.claim_repository import ClaimRepository  # noqa: E402
from app.repositories.json_store import JsonStore  # noqa: E402
from app.services.policy_engine import PolicyEngine  # noqa: E402
from tests.helpers import DEMO_PASSWORDS, POLICY_FILE, make_settings, wait_until  # noqa: E402


# ------------------------------------------------------------------ safety nets


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any code path tries to open a real connection (Ollama, Anthropic, ...).

    Tests that exercise HTTP providers inject ``httpx.MockTransport`` or a fake SDK client instead.
    """

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Real network access is disabled in unit tests")

    async def refuse_async(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Real network access is disabled in unit tests")

    for module in (httpx, httpx2):
        monkeypatch.setattr(module.HTTPTransport, "handle_request", refuse)
        monkeypatch.setattr(module.AsyncHTTPTransport, "handle_async_request", refuse_async)


# ---------------------------------------------------------------- core objects


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def policy() -> Policy:
    """The real company policy from config/policy.yaml (fresh copy per test)."""
    return Policy.load(POLICY_FILE)


@pytest.fixture
def engine(policy: Policy) -> PolicyEngine:
    return PolicyEngine(policy, base_currency="INR", low_confidence_threshold=0.6)


@pytest.fixture
def store(tmp_path: Path) -> JsonStore:
    return JsonStore(tmp_path / "db.json")


@pytest.fixture
def claim_repo(store: JsonStore) -> ClaimRepository:
    return ClaimRepository(store)


@pytest.fixture
def container(settings: Settings) -> Container:
    """A fully wired application container on temporary storage, with its own event bus."""
    c = Container(settings)
    c.bus = EventBus()
    return c


# ----------------------------------------------------------------------- API


@dataclass
class ApiHarness:
    """A TestClient bound to an isolated container, plus helpers for the common calls."""

    client: TestClient
    container: Container
    app: FastAPI
    tokens: dict[str, str] = field(default_factory=dict)

    def token(self, username: str = "employee") -> str:
        if username not in self.tokens:
            response = self.client.post(
                "/api/auth/login", json={"username": username, "password": DEMO_PASSWORDS[username]}
            )
            assert response.status_code == 200, response.text
            self.tokens[username] = response.json()["access_token"]
        return self.tokens[username]

    def headers(self, username: str = "employee") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(username)}"}

    def get(self, url: str, user: str = "employee", **kwargs: Any) -> httpx2.Response:
        return self.client.get(url, headers=self.headers(user), **kwargs)

    def post(self, url: str, user: str = "employee", **kwargs: Any) -> httpx2.Response:
        return self.client.post(url, headers=self.headers(user), **kwargs)

    def patch(self, url: str, user: str = "employee", **kwargs: Any) -> httpx2.Response:
        return self.client.patch(url, headers=self.headers(user), **kwargs)

    def put(self, url: str, user: str = "employee", **kwargs: Any) -> httpx2.Response:
        return self.client.put(url, headers=self.headers(user), **kwargs)

    def delete(self, url: str, user: str = "employee", **kwargs: Any) -> httpx2.Response:
        return self.client.delete(url, headers=self.headers(user), **kwargs)

    def create_claim(self, user: str = "employee", **body: Any) -> dict:
        response = self.post("/api/claims", user, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def claim(self, claim_id: str, user: str = "employee") -> dict:
        response = self.get(f"/api/claims/{claim_id}", user)
        assert response.status_code == 200, response.text
        return response.json()

    def upload(self, claim_id: str, files: list[tuple[str, bytes, str | None]], user: str = "employee"):
        multipart = [("files", (name, content, ctype or "application/octet-stream")) for name, content, ctype in files]
        return self.post(f"/api/claims/{claim_id}/receipts", user, files=multipart)

    def settle(self, timeout: float = 20.0) -> None:
        """Wait until the agent pipeline and the mock finance system have no background work left."""
        agent, gateway = self.container.agent, self.container.gateway
        wait_until(lambda: not agent._tasks and not gateway._tasks, timeout=timeout, message="background tasks")

    def process(self, claim_id: str, files: list[tuple[str, bytes, str | None]], user: str = "employee") -> dict:
        """Upload files, wait for the background pipeline to finish and return the refreshed claim."""
        response = self.upload(claim_id, files, user)
        assert response.status_code == 202, response.text
        self.settle()
        return self.claim(claim_id, user)


@pytest.fixture
def api_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., ApiHarness]]:
    """Build the real FastAPI app around a fresh container on temporary storage.

    The module-level ``container`` references used by ``app.api.deps`` (auth/ownership guards and
    ``get_container``), ``app.main`` (lifespan, app factory) and ``app.container`` are all swapped.
    ``setup(container)`` runs before startup, e.g. to seed data for the lifespan resume logic.
    """
    import app.api.deps as deps_module
    import app.container as container_module
    import app.main as main_module

    opened: list[ApiHarness] = []

    def factory(setup: Callable[[Container], None] | None = None, **sections: Any) -> ApiHarness:
        assert not opened, "one API harness per test"
        c = Container(make_settings(tmp_path / "api", **sections))
        c.bus = EventBus()
        if setup:
            setup(c)
        for module in (container_module, deps_module, main_module):
            monkeypatch.setattr(module, "container", c)
        application = main_module.create_app()
        client = TestClient(application)
        client.__enter__()  # runs the lifespan (resume logic) on the client's event-loop thread
        harness = ApiHarness(client, c, application)
        opened.append(harness)
        return harness

    yield factory
    for harness in opened:
        try:
            harness.settle(timeout=10)
        finally:
            harness.client.__exit__(None, None, None)


@pytest.fixture
def api(api_factory: Callable[..., ApiHarness]) -> ApiHarness:
    return api_factory()
