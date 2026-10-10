"""Typed application settings.

Values are layered (highest priority first):
  1. environment variables  (ERA_LLM__PROVIDER=claude)
  2. .env file
  3. config/settings.yaml
  4. defaults declared below
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

BASE_DIR = Path(__file__).resolve().parents[2]
SETTINGS_FILE = BASE_DIR / "config" / "settings.yaml"

ProviderName = Literal["ollama", "claude", "mock"]


class AppSection(BaseModel):
    name: str = "Expense & Reimbursement Agent"
    agent_name: str = "Rika"
    company: str = "Acme Corp"
    base_currency: str = "INR"


class ServerSection(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8100
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5200"])


class AuthSection(BaseModel):
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    token_ttl_minutes: int = 480
    users_file: str = "data/users.json"
    show_demo_users: bool = True


class StorageSection(BaseModel):
    database_file: str = "storage/db.json"
    upload_dir: str = "storage/uploads"
    max_upload_mb: int = 15
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".png", ".jpg", ".jpeg", ".webp"]
    )


class PolicySection(BaseModel):
    file: str = "config/policy.yaml"


class OllamaSection(BaseModel):
    base_url: str = "http://localhost:11434"
    vision_model: str = "gemma3:4b"
    chat_model: str = "gemma3:4b"
    timeout_seconds: int = 180
    keep_alive: str = "10m"
    zoom_tiles: bool = True


class ClaudeSection(BaseModel):
    api_key: str = ""
    vision_model: str = "claude-opus-5-5"
    chat_model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    chat_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = 16000
    timeout_seconds: int = 180
    native_pdf: bool = True
    server_fallbacks: bool = True


class LLMSection(BaseModel):
    provider: ProviderName = "ollama"
    fallback_chain: list[ProviderName] = Field(default_factory=lambda: ["mock"])
    temperature: float = 0.1
    max_concurrency: int = 2
    ollama: OllamaSection = OllamaSection()
    claude: ClaudeSection = ClaudeSection()


class PipelineSection(BaseModel):
    stage_delay_ms: int = 450
    pdf_render_dpi: int = 150
    max_pdf_pages: int = 3
    low_confidence_threshold: float = 0.6
    verify_mode: Literal["auto", "always", "off"] = "auto"


class ReimbursementSection(BaseModel):
    reference_prefix: str = "EXP"
    manager_approval_required: bool = True
    auto_approve_below: float = 0
    payout_delay_seconds: int = 25


class NotificationSection(BaseModel):
    max_per_user: int = 200
    heartbeat_seconds: int = 15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ERA_",
        env_nested_delimiter="__",
        env_file=BASE_DIR / ".env",
        extra="ignore",
        yaml_file=SETTINGS_FILE,
    )

    app: AppSection = AppSection()
    server: ServerSection = ServerSection()
    auth: AuthSection = AuthSection()
    storage: StorageSection = StorageSection()
    policy: PolicySection = PolicySection()
    llm: LLMSection = LLMSection()
    pipeline: PipelineSection = PipelineSection()
    reimbursement: ReimbursementSection = ReimbursementSection()
    notifications: NotificationSection = NotificationSection()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    def resolve_path(self, relative: str) -> Path:
        """Resolve a config path relative to the backend directory."""
        path = Path(relative)
        return path if path.is_absolute() else BASE_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
