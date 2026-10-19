import json

import httpx
import pytest
from pydantic import SecretStr

from core.config import Settings, get_settings
from core.logging import redact, redact_known, register_secret
from core.schemas import HypothesisSet, PatchDraft
from providers.base import AgentRequest, ProviderError, extract_json
from providers.meta import MetaModelProvider
from providers.mock import MockProvider
from providers.openai_compat import OpenAICompatibleProvider
from providers.registry import build_provider
from services.settings_service import env_defaults

HYP = {
    "reasoning_summary": "x",
    "hypotheses": [
        {"key": "H1", "title": "a", "explanation": "b", "prior": 0.5},
        {"key": "H2", "title": "c", "explanation": "d", "prior": 0.3},
    ],
}


def _request(task="hypotheses", **ctx):
    return AgentRequest(agent="hypothesis_generator", task=task, system="sys", user="usr", context=ctx)


def test_mock_selects_scenario_and_flags_simulation():
    target = "payment capture > charges the customer exactly once when a timed-out request is retried"
    completion = MockProvider().generate(_request(target_test=target), HypothesisSet)
    assert completion.simulated
    assert completion.usage.estimated
    assert completion.output.hypotheses[0].title.startswith("A new idempotency key")


def test_mock_repair_attempts_are_indexed():
    target = "charges the customer exactly once when a timed-out request is retried"
    first = MockProvider().generate(_request("repair", target_test=target, attempt=0), PatchDraft).output
    second = MockProvider().generate(_request("repair", target_test=target, attempt=1), PatchDraft).output
    assert first.summary != second.summary
    exhausted = MockProvider().generate(_request("repair", target_test=target, attempt=9), PatchDraft).output
    assert exhausted.edits == []


def test_mock_never_fabricates_patches_for_unknown_failures():
    patch = MockProvider().generate(_request("repair", target_test="some unrelated test"), PatchDraft).output
    assert patch.edits == []
    assert "[mock]" in patch.summary


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": 2} hope that helps') == {"a": 2}


def _provider(handler, **kw):
    return OpenAICompatibleProvider(
        name="openai",
        base_url="https://example.test/v1",
        api_key="sk-test-secret-123456",
        model="m",
        temperature=0.2,
        max_tokens=100,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
        **kw,
    )


def _completion(content, usage=(10, 5)):
    return httpx.Response(
        200,
        json={
            "model": "m",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)},
        },
    )


def test_openai_compatible_parses_and_counts_usage():
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer sk-test-secret-123456"
        return _completion(json.dumps(HYP))

    completion = _provider(handler).generate(_request(), HypothesisSet)
    assert not completion.simulated
    assert completion.usage.prompt_tokens == 10 and completion.usage.completion_tokens == 5
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["max_tokens"] == 100


def test_invalid_output_triggers_one_repair_round():
    replies = iter([_completion('{"hypotheses": "nope"}'), _completion(json.dumps(HYP))])
    completion = _provider(lambda r: next(replies)).generate(_request(), HypothesisSet)
    assert len(completion.output.hypotheses) == 2
    assert completion.usage.prompt_tokens == 20


def test_persistent_invalid_output_raises():
    with pytest.raises(ProviderError, match="schema validation"):
        _provider(lambda r: _completion("not json at all")).generate(_request(), HypothesisSet)


def test_rejected_response_format_is_downgraded():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, text='{"error": "unsupported response_format"}')
        return _completion(json.dumps(HYP))

    provider = _provider(handler, structured_output="json_schema")
    provider.generate(_request(), HypothesisSet)
    assert bodies[0]["response_format"]["type"] == "json_schema"
    assert bodies[1]["response_format"]["type"] == "json_object"


def test_meta_provider_matches_documented_contract():
    bodies = []

    def handler(request: httpx.Request):
        assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer meta-test-key-000"
        bodies.append(json.loads(request.content))
        return _completion(json.dumps(HYP))

    settings = Settings(meta_api_key=SecretStr("meta-test-key-000"), meta_reasoning_effort="low")
    provider = MetaModelProvider(settings, transport=httpx.MockTransport(handler))
    provider.generate(_request(), HypothesisSet)
    body = bodies[0]
    assert body["model"] == "muse-spark-1.3"
    assert "max_completion_tokens" in body and "max_tokens" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "HypothesisSet"
    assert body["reasoning_effort"] == "low"
    for forbidden in ("stop", "logit_bias", "logprobs"):
        assert forbidden not in body


def test_meta_falls_back_to_mock_without_key():
    assert get_settings().resolved_meta_key is None
    selection = build_provider(env_defaults().model_copy(update={"ai_provider": "meta"}))
    assert selection.provider.name == "mock"
    assert "META_API_KEY" in (selection.fallback_reason or "")


def test_meta_check_without_key_reports_not_configured():
    provider = MetaModelProvider(Settings(meta_api_key=None, model_api_key=None))
    result = provider.check()
    assert result["ok"] is False and "META_API_KEY" in result["detail"]


def test_secrets_are_redacted():
    register_secret("super-secret-value-42")
    assert "super-secret-value-42" not in redact_known("token is super-secret-value-42")
    assert redact("Authorization: Bearer abc.def") == "Authorization: Bearer ***"
    assert "gho_" not in redact("leaked gho_abcdefghijklmnop")
    assert "hunter2" not in redact('{"api_key": "hunter2"}')
