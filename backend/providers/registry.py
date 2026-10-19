"""Builds the configured provider, falling back to mock mode when credentials are missing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config import get_settings
from providers.base import AIProvider
from providers.meta import MetaModelProvider
from providers.mock import MockProvider
from providers.openai_compat import OpenAICompatibleProvider
from services.settings_service import RuntimeConfig

log = logging.getLogger(__name__)


@dataclass
class ProviderSelection:
    provider: AIProvider
    requested: str
    fallback_reason: str | None = None


def build_provider(config: RuntimeConfig) -> ProviderSelection:
    settings = get_settings()
    requested = config.ai_provider
    if requested == "meta":
        if settings.resolved_meta_key is None:
            reason = "AI_PROVIDER=meta but META_API_KEY is not set; using the mock provider instead."
            log.warning(reason)
            return ProviderSelection(MockProvider(), requested, reason)
        return ProviderSelection(
            MetaModelProvider(
                settings,
                model=config.meta_model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            ),
            requested,
        )
    if requested == "openai":
        key = settings.openai_compat_api_key
        return ProviderSelection(
            OpenAICompatibleProvider(
                name="openai",
                base_url=settings.openai_compat_base_url,
                api_key=key.get_secret_value() if key else None,
                model=config.openai_compat_model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout_s=settings.ai_timeout_s,
                structured_output=settings.openai_compat_structured_output,
            ),
            requested,
        )
    return ProviderSelection(MockProvider(), requested)
