"""Meta Model API contract tests (mock HTTP transport; no network, no credentials, no cost).

Behaviour is checked against dev.meta.ai: chat-completions request fields, CompletionUsage
(cached/reasoning token details), finish_reason values, the {"error": {...}} envelope and the
documented retry policy (429/503 honour Retry-After, 504 is not retried unchanged).
"""

import json

import httpx
import pytest
from pydantic import SecretStr

import providers.openai_compat as compat
from agents.base import AgentError, Budget, InvestigationContext
from core.config import Settings
from core.schemas import HypothesisSet
from providers.base import AgentRequest, ProviderError, Usage
from providers.meta import MetaModelProvider

HYP = {
    "reasoning_summary": "x",
    "hypotheses": [
        {"key": "H1", "title": "a", "explanation": "b", "prior": 0.5},
        {"key": "H2", "title": "c", "explanation": "d", "prior": 0.3},
    ],
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(compat.time, "sleep", lambda s: slept.append(s))
    return slept


def provider(handler, **settings):
    s = Settings(meta_api_key=SecretStr("meta-test-key-000"), **settings)
    return MetaModelProvider(s, transport=httpx.MockTransport(handler))


def request():
    return AgentRequest(agent="hypothesis_generator", task="hypotheses", system="sys", user="usr")


def completion(content, *, finish="stop", usage=None, refusal=None):
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "model": "muse-spark-1.3",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content, "refusal": refusal},
                    "finish_reason": finish,
                }
            ],
            "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        },
    )


def error(status, message, *, type_="invalid_request_error", code=None, param=None, headers=None):
    body = {"error": {"message": message, "type": type_, "param": param, "code": code}}
    return httpx.Response(status, json=body, headers=headers or {})


def test_request_body_matches_documented_contract():
    bodies = []

    def handler(req: httpx.Request):
        bodies.append(json.loads(req.content))
        return completion(json.dumps(HYP))

    provider(handler, meta_reasoning_effort="medium").generate(request(), HypothesisSet)
    body = bodies[0]
    assert set(body) == {
        "model",
        "messages",
        "max_completion_tokens",
        "temperature",
        "response_format",
        "reasoning_effort",
    }
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    schema = body["response_format"]["json_schema"]
    assert schema["name"] == "HypothesisSet" and schema["strict"] is False
    assert "$ref" not in json.dumps(schema["schema"]) and "$defs" not in json.dumps(schema["schema"])


def test_usage_details_are_accounted_and_priced():
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 200_000,
        "total_tokens": 1_200_000,
        "prompt_tokens_details": {"cached_tokens": 400_000},
        "completion_tokens_details": {"reasoning_tokens": 150_000},
    }
    result = provider(lambda r: completion(json.dumps(HYP), usage=usage)).generate(request(), HypothesisSet)
    assert (result.usage.cached_tokens, result.usage.reasoning_tokens) == (400_000, 150_000)
    budget = Budget(
        1, 1, 1, 1, 60, price_input_per_m=1.25, price_output_per_m=4.25, price_cached_input_per_m=0.15
    )
    budget.record(result.usage)
    # 600k uncached x 1.25 + 400k cached x 0.15 + 200k output x 4.25 (Muse Spark 1.3 standard list price)
    assert budget.estimated_cost_usd == pytest.approx(0.75 + 0.06 + 0.85)
    assert budget.usage()["reasoning_tokens"] == 150_000


def test_rate_limit_honours_retry_after(no_sleep):
    replies = iter(
        [
            error(
                429,
                "Rate limit exceeded",
                type_="rate_limit_error",
                code="rate_limit_exceeded",
                headers={"Retry-After": "15"},
            ),
            completion(json.dumps(HYP)),
        ]
    )
    provider(lambda r: next(replies)).generate(request(), HypothesisSet)
    assert no_sleep == [15.0]


def test_service_unavailable_is_retried_with_capped_backoff(no_sleep):
    replies = iter([error(503, "overloaded", headers={"Retry-After": "600"}), completion(json.dumps(HYP))])
    provider(lambda r: next(replies)).generate(request(), HypothesisSet)
    assert no_sleep == [compat.OpenAICompatibleProvider.MAX_RETRY_AFTER_S]


def test_server_errors_give_up_after_max_attempts(no_sleep):
    calls = []

    def handler(r):
        calls.append(1)
        return error(500, "boom", type_="server_error")

    with pytest.raises(ProviderError, match="HTTP 500"):
        provider(handler).generate(request(), HypothesisSet)
    assert len(calls) == compat.OpenAICompatibleProvider.MAX_ATTEMPTS
    assert len(no_sleep) == compat.OpenAICompatibleProvider.MAX_ATTEMPTS - 1


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413, 504])
def test_non_retryable_statuses_fail_immediately(status, no_sleep):
    calls = []

    def handler(r):
        calls.append(1)
        return error(status, "nope", code="invalid_api_key" if status == 401 else None)

    with pytest.raises(ProviderError) as info:
        provider(handler).generate(request(), HypothesisSet)
    assert len(calls) == 1 and no_sleep == []
    assert info.value.status == status
    if status == 401:
        assert "invalid_api_key" in str(info.value) and "META_API_KEY" in str(info.value)
    if status == 504:
        assert "not retried" in str(info.value)


def test_error_envelope_message_is_surfaced():
    with pytest.raises(ProviderError, match=r"HTTP 403 \(permission_error\): model not enabled"):
        provider(lambda r: error(403, "model not enabled", type_="permission_error")).generate(
            request(), HypothesisSet
        )


def test_schema_rejection_downgrades_structured_output():
    formats = []

    def handler(req):
        body = json.loads(req.content)
        formats.append(body.get("response_format", {}).get("type"))
        if formats[-1] == "json_schema":
            return error(400, "unsupported keyword", param="response_format.json_schema.schema")
        return completion(json.dumps(HYP))

    p = provider(handler)
    p.generate(request(), HypothesisSet)
    assert formats == ["json_schema", "json_object"]
    assert p.structured_output == "json_object"


def test_unrelated_400_is_not_masked_by_downgrade():
    with pytest.raises(ProviderError, match="context length"):
        provider(lambda r: error(400, "maximum context length exceeded", param="messages")).generate(
            request(), HypothesisSet
        )


def test_truncated_output_fails_fast_with_usage():
    calls = []

    def handler(r):
        calls.append(1)
        return completion('{"reasoning_summary": "cut', finish="length")

    with pytest.raises(ProviderError, match="truncated at max_completion_tokens") as info:
        provider(handler).generate(request(), HypothesisSet)
    assert len(calls) == 1  # no doomed repair round
    assert info.value.usage.prompt_tokens == 100 and info.value.usage.completion_tokens == 50


def test_refusal_and_content_filter_are_reported():
    with pytest.raises(ProviderError, match="refused the request: not allowed"):
        provider(lambda r: completion(None, refusal="not allowed")).generate(request(), HypothesisSet)
    with pytest.raises(ProviderError, match="content filter"):
        provider(lambda r: completion(None, finish="content_filter")).generate(request(), HypothesisSet)


def test_tokens_spent_on_failed_calls_are_counted_in_the_budget(tmp_path):
    from core.database import session_scope
    from core.models import Investigation, ModelCall, Repository

    with session_scope() as db:
        repo = Repository(name="r", source_type="local", source="x", snapshot_path=str(tmp_path), profile={})
        db.add(repo)
        db.flush()
        inv = Investigation(repository_id=repo.id, title="t", usage={}, budget={})
        db.add(inv)
        db.flush()
        inv_id = inv.id
    bad = provider(lambda r: completion('{"hypotheses": "nope"}'))
    budget = Budget(5, 1, 1, 1, 60, price_input_per_m=1.25, price_output_per_m=4.25)
    ctx = InvestigationContext(
        investigation_id=inv_id,
        repository_name="r",
        snapshot=tmp_path,
        mode="forge",
        symptom="",
        target_test=None,
        provider=bad,
        sandbox=None,  # type: ignore[arg-type]
        workspaces=None,  # type: ignore[arg-type]
        budget=budget,
    )
    with pytest.raises(AgentError):
        ctx.call_model(
            agent="hypothesis_generator",
            task="hypotheses",
            system="s",
            user="u",
            context={},
            schema=HypothesisSet,
        )
    # two billed requests (original + one repair round) before the failure
    assert (budget.prompt_tokens, budget.completion_tokens, budget.failed_calls) == (200, 100, 1)
    with session_scope() as db:
        call = db.query(ModelCall).filter_by(investigation_id=inv_id).one()
        assert not call.ok and call.prompt_tokens == 200


def test_usage_add_tolerates_missing_details():
    u = Usage()
    u.add({"prompt_tokens": 5, "completion_tokens": 2})
    u.add(None)
    assert (u.prompt_tokens, u.completion_tokens, u.cached_tokens, u.requests) == (5, 2, 0, 2)
