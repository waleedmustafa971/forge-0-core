"""Meta Model API provider (Muse Spark).

Verified against Meta's documentation (dev.meta.ai, October 2026):

* Base URL ``https://api.meta.ai/v1``; ``POST /chat/completions``; ``GET /models``.
* Auth: ``Authorization: Bearer <key>`` (Meta's examples name the variable MODEL_API_KEY;
  FORGE-0 reads META_API_KEY and falls back to MODEL_API_KEY).
* Output limit parameter is ``max_completion_tokens`` (``max_tokens`` is a deprecated alias).
* ``temperature`` 0–2; ``reasoning_effort`` minimal|low|medium|high|xhigh.
* Structured output via ``response_format`` = ``{"type": "json_schema", "json_schema": {...}}``.
* ``stop``, ``logit_bias`` and ``logprobs: true`` return HTTP 400, so they are never sent.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.config import Settings
from providers.openai_compat import OpenAICompatibleProvider


class MetaModelProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = settings.resolved_meta_key
        extra: dict[str, Any] = {}
        if settings.meta_reasoning_effort:
            extra["reasoning_effort"] = settings.meta_reasoning_effort
        super().__init__(
            name="meta",
            base_url=settings.meta_api_base_url,
            api_key=key.get_secret_value() if key else None,
            model=model or settings.meta_model,
            temperature=settings.ai_temperature if temperature is None else temperature,
            max_tokens=max_tokens or settings.ai_max_tokens,
            timeout_s=settings.ai_timeout_s,
            structured_output=settings.meta_structured_output,
            token_param="max_completion_tokens",  # noqa: S106 - a request field name, not a secret
            extra_body=extra,
            transport=transport,
        )
