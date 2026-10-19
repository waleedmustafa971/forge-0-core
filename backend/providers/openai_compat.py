"""OpenAI-compatible Chat Completions provider (also the transport for Meta's Model API)."""

from __future__ import annotations

import json
import logging
import random
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from core.logging import register_secret
from providers.base import AgentRequest, AIProvider, Completion, ProviderError, T, Usage, extract_json

log = logging.getLogger(__name__)

StructuredMode = Literal["json_schema", "json_object", "none"]


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolves local `$ref`s into `$defs` so the schema is self-contained.

    Meta's docs accept "a JSON Schema object" without listing keyword restrictions; inlining
    avoids depending on `$ref` support. FORGE-0's contracts are not recursive.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise ValueError("schema nesting too deep to inline")
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = resolve(defs[ref.split("/")[-1]], depth + 1)
                extra = {k: resolve(v, depth + 1) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            return {k: resolve(v, depth + 1) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v, depth + 1) for v in node]
        return node

    return resolve(schema)


def schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object and nothing else (no prose, no code fences). "
        "It must validate against this JSON Schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


class OpenAICompatibleProvider(AIProvider):
    simulated = False

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str | None,
        model: str,
        temperature: float | None,
        max_tokens: int,
        timeout_s: float,
        structured_output: StructuredMode = "json_object",
        token_param: str = "max_tokens",  # noqa: S107 - a request field name, not a secret
        extra_body: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        register_secret(api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.structured_output: StructuredMode = structured_output
        self.token_param = token_param
        self.extra_body = extra_body or {}
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    # -- HTTP -----------------------------------------------------------------
    # Retry policy follows Meta's error-handling guide (dev.meta.ai/docs/error-handling):
    # 429/500/502/503 are retried with backoff and Retry-After is honoured; 504 means the
    # server time limit was hit and must not be retried unchanged; 400/401/402/403/404/413
    # are caller errors and are never retried.
    RETRYABLE = frozenset({408, 409, 429, 500, 502, 503})
    MAX_ATTEMPTS = 4
    MAX_RETRY_AFTER_S = 120.0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            return max(0.0, when.timestamp() - time.time())

    def _http_error(self, resp: httpx.Response) -> ProviderError:
        """Builds an error from the {"error": {message, type, param, code}} envelope."""
        message, kind, param, code = resp.text[:500], None, None, None
        try:
            envelope = resp.json().get("error")
            if isinstance(envelope, dict):
                message = str(envelope.get("message") or message)[:500]
                kind, param, code = envelope.get("type"), envelope.get("param"), envelope.get("code")
        except (ValueError, AttributeError):
            pass
        status = resp.status_code
        hints = {
            401: "check META_API_KEY / OPENAI_COMPAT_API_KEY",
            402: "billing is not configured for this account",
            403: "the key has no access to this model or endpoint",
            404: "unknown model or path; check the model id and base URL",
            413: "request body too large; reduce the context sent to the model",
            504: "server time limit exceeded; reduce input size, AI_MAX_TOKENS or META_REASONING_EFFORT "
            "(not retried, per the provider's guidance)",
        }
        detail = " ".join(str(x) for x in (kind, code) if x)
        text = f"{self.name} HTTP {status}{f' ({detail})' if detail else ''}: {message}"
        if status in hints:
            text += f" - {hints[status]}"
        return ProviderError(
            text,
            retryable=status in self.RETRYABLE,
            status=status,
            retry_after_s=self._retry_after(resp),
            param=str(param) if param else None,
        )

    def _sleep_before_retry(self, attempt: int, err: ProviderError) -> None:
        if err.retry_after_s is not None:
            delay = min(err.retry_after_s, self.MAX_RETRY_AFTER_S)
        else:
            delay = min(30.0, 1.0 * 2**attempt) * (0.5 + random.random() / 2)  # noqa: S311 - jitter
        log.warning(
            "provider request failed, retrying",
            extra={"provider": self.name, "error": str(err)[:300], "delay_s": round(delay, 2)},
        )
        time.sleep(delay)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                resp = self._client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
            except httpx.TimeoutException as exc:
                err = ProviderError(f"{self.name} request timed out: {exc}", retryable=True)
            except httpx.HTTPError as exc:
                err = ProviderError(f"{self.name} connection error: {exc}", retryable=True)
            else:
                if resp.status_code < 300:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise ProviderError(f"{self.name} returned a non-JSON response") from exc
                err = self._http_error(resp)
            if not err.retryable or attempt == self.MAX_ATTEMPTS - 1:
                raise err
            self._sleep_before_retry(attempt, err)
        raise AssertionError("unreachable")

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any] | None:
        if self.structured_output == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^A-Za-z0-9_-]", "_", schema.__name__)[:64],
                    "schema": inline_refs(schema.model_json_schema()),
                    "strict": False,
                },
            }
        if self.structured_output == "json_object":
            return {"type": "json_object"}
        return None

    def _body(self, messages: list[dict[str, str]], schema: type[BaseModel] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, self.token_param: self.max_tokens}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if schema is not None:
            fmt = self._response_format(schema)
            if fmt:
                body["response_format"] = fmt
        body.update(self.extra_body)
        return body

    def _is_format_rejection(self, exc: ProviderError) -> bool:
        if exc.status != 400 or self.structured_output == "none":
            return False
        text = f"{exc.param or ''} {exc}".lower()
        return any(k in text for k in ("response_format", "json_schema", "schema", "structured"))

    def _complete(self, messages: list[dict[str, str]], schema: type[BaseModel]) -> dict[str, Any]:
        try:
            return self._post("/chat/completions", self._body(messages, schema))
        except ProviderError as exc:
            if not self._is_format_rejection(exc):
                raise
            previous = self.structured_output
            self.structured_output = "json_object" if previous == "json_schema" else "none"
            log.warning(
                "structured output rejected; downgrading",
                extra={"provider": self.name, "from": previous, "to": self.structured_output},
            )
            return self._complete(messages, schema)

    # -- AIProvider -------------------------------------------------------------
    def generate(self, request: AgentRequest, schema: type[T]) -> Completion[T]:
        messages = [
            {"role": "system", "content": f"{request.system}\n\n{schema_instructions(schema)}"},
            {"role": "user", "content": request.user},
        ]
        usage = Usage()
        started = time.monotonic()
        last_error = ""

        def fail(message: str) -> ProviderError:
            usage.latency_ms = int((time.monotonic() - started) * 1000)
            return ProviderError(message, usage=usage)

        for _validation_attempt in range(2):
            try:
                data = self._complete(messages, schema)
            except ProviderError as exc:
                if usage.requests:
                    exc.usage = usage
                raise
            usage.add(data.get("usage"))
            try:
                choice = data["choices"][0]
                message = choice.get("message") or {}
            except (KeyError, IndexError, TypeError, AttributeError) as exc:
                raise fail(f"{self.name} returned an unexpected response shape") from exc
            finish = choice.get("finish_reason")
            text = message.get("content")
            if isinstance(text, list):  # tolerate content-part arrays from other compatible servers
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            if not text:
                refusal = message.get("refusal")
                if refusal:
                    raise fail(f"{self.name} refused the request: {str(refusal)[:300]}")
                if finish == "content_filter":
                    raise fail(f"{self.name} response was blocked by the content filter")
                if finish == "length":
                    raise fail(
                        f"{self.name} produced no output before reaching max_completion_tokens "
                        f"({self.max_tokens}); raise AI_MAX_TOKENS or lower META_REASONING_EFFORT"
                    )
                text = ""
            try:
                output = schema.model_validate(extract_json(text))
                usage.latency_ms = int((time.monotonic() - started) * 1000)
                return Completion(output, usage, self.name, data.get("model") or self.model, False, text)
            except (ValueError, ValidationError) as exc:
                if finish == "length":
                    # A correction request would be truncated again; fail with a precise hint.
                    raise fail(
                        f"{self.name} output was truncated at max_completion_tokens ({self.max_tokens}); "
                        "raise AI_MAX_TOKENS or lower META_REASONING_EFFORT"
                    ) from exc
                last_error = str(exc)[:1500]
                messages += [
                    {"role": "assistant", "content": text[:8000]},
                    {
                        "role": "user",
                        "content": "Your reply did not validate against the required schema:\n"
                        f"{last_error}\nReturn the corrected JSON object only.",
                    },
                ]
        raise fail(f"{self.name} output failed schema validation: {last_error}")

    def check(self, deep: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"provider": self.name, "model": self.model, "base_url": self.base_url}
        if not self._api_key and self.name == "meta":
            return {**result, "ok": False, "detail": "META_API_KEY is not configured"}
        started = time.monotonic()
        try:
            resp = self._client.get(f"{self.base_url}/models", headers=self._headers())
            result["models_status"] = resp.status_code
            if resp.status_code < 300:
                payload = resp.json()
                ids = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
                result["models"] = ids[:50]
                result["model_listed"] = self.model in ids if ids else None
            else:
                result["detail"] = resp.text[:300]
            if deep:
                data = self._post(
                    "/chat/completions",
                    self._body([{"role": "user", "content": "Reply with the single word OK."}], None)
                    | {self.token_param: 16},
                )
                result["completion_ok"] = True
                result["completion_model"] = data.get("model")
                result["completion_usage"] = data.get("usage")
            result["ok"] = resp.status_code < 300 and (not deep or result.get("completion_ok", False))
        except (httpx.HTTPError, ProviderError, ValueError) as exc:
            result["ok"] = False
            result["detail"] = str(exc)[:300]
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        return result
