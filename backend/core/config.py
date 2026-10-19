"""Application configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

ProviderName = Literal["mock", "meta", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    database_url: str = "postgresql+psycopg://forge:forge@127.0.0.1:5433/forge0"
    db_pool_size: int = 10
    data_dir: Path = REPO_ROOT / "data"

    # --- Authentication ---------------------------------------------------
    auth_mode: Literal["local", "token"] = "local"
    forge_api_token: SecretStr | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- AI providers -------------------------------------------------------
    ai_provider: ProviderName = "mock"
    ai_max_tokens: int = 4096
    ai_temperature: float = 0.2
    ai_timeout_s: float = 180.0
    ai_price_input_per_m: float = 1.25
    ai_price_output_per_m: float = 4.25
    ai_price_cached_input_per_m: float = 0.15

    meta_api_key: SecretStr | None = None
    model_api_key: SecretStr | None = None  # name used in Meta's own documentation
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_model: str = "muse-spark-1.3"
    meta_reasoning_effort: Literal["", "minimal", "low", "medium", "high", "xhigh"] = ""
    meta_structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"

    openai_compat_api_key: SecretStr | None = None
    openai_compat_base_url: str = "http://localhost:11434/v1"
    openai_compat_model: str = "llama3.1"
    openai_compat_structured_output: Literal["json_schema", "json_object", "none"] = "json_object"

    # --- Sandbox --------------------------------------------------------------
    sandbox_docker_command: str = "auto"
    sandbox_wsl_distro: str = ""
    sandbox_wsl_keepalive: bool = True
    sandbox_node_image: str = "node:24-alpine"
    sandbox_python_image: str = "forge0/sandbox-python:3.12"
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "512m"
    sandbox_pids_limit: int = 128
    sandbox_timeout_s: int = 60
    sandbox_workdir_size: str = "256m"
    sandbox_max_output_bytes: int = 64_000
    sandbox_max_upload_bytes: int = 50_000_000
    sandbox_max_concurrent: int = 2

    # --- Investigation budgets -------------------------------------------------
    max_experiments: int = 8
    max_model_calls: int = 24
    max_repair_attempts: int = 3
    max_experiment_rounds: int = 3
    investigation_time_budget_s: int = 900
    worker_threads: int = 2
    keep_workspaces: bool = False

    # --- Repositories -------------------------------------------------------
    import_allowed_roots: str = Field(default="", description="Comma-separated extra roots for local imports")
    seed_demo: bool = True

    # --- Lite mode -------------------------------------------------------------
    # When set, the backend also serves the prebuilt dashboard (frontend/dist) so no
    # Node/Vite process is needed. Relative paths resolve against the repository root.
    serve_frontend_dir: str = ""

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_import_roots(self) -> list[Path]:
        roots = [REPO_ROOT / "demo", self.data_dir / "uploads"]
        roots += [Path(p.strip()).resolve() for p in self.import_allowed_roots.split(",") if p.strip()]
        return roots

    @property
    def resolved_meta_key(self) -> SecretStr | None:
        for key in (self.meta_api_key, self.model_api_key):
            if key is not None and key.get_secret_value().strip():
                return key
        return None

    @property
    def demo_repo_path(self) -> Path:
        return REPO_ROOT / "demo" / "order-management"


@lru_cache
def get_settings() -> Settings:
    return Settings()
