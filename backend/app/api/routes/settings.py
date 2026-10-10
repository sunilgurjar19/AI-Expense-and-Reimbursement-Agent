from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import AppContainer, CurrentUser
from app.container import Container
from app.core.config import ProviderName
from app.models.api import LLMSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _llm_state(app: Container) -> dict:
    return {
        "active": app.llm.active,
        "fallback_chain": app.settings.llm.fallback_chain,
        "providers": [asdict(s) for s in app.llm.statuses()],
    }


@router.get("/llm")
def get_llm_settings(_: CurrentUser, app: AppContainer) -> dict:
    return _llm_state(app)


@router.put("/llm")
def set_llm_provider(body: LLMSettingsUpdate, _: CurrentUser, app: AppContainer) -> dict:
    """Switch the active provider at runtime (not persisted - edit settings.yaml for that)."""
    app.llm.set_active(body.provider)
    return _llm_state(app)


@router.post("/llm/{provider}/test")
async def test_provider(provider: ProviderName, _: CurrentUser, app: AppContainer) -> dict:
    return asdict(await app.llm.health_check(provider))
