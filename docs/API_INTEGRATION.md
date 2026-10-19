# Meta Model API integration

FORGE-0 runs fully in **mock mode** without credentials. Connecting Muse Spark requires no code
changes.

## Verified API contract

Checked against Meta's documentation at [dev.meta.ai](https://dev.meta.ai/docs) on 2026-10-19
(chat completions feature page, API reference, schemas, list-models, pricing pages):

| Item | Value used by FORGE-0 |
| --- | --- |
| Base URL | `https://api.meta.ai/v1` (`META_API_BASE_URL`) |
| Chat endpoint | `POST /chat/completions` |
| Model listing | `GET /models` (used by the connectivity check; costs no tokens) |
| Authentication | `Authorization: Bearer <key>`. Meta's examples name the variable `MODEL_API_KEY`; FORGE-0 reads `META_API_KEY` and falls back to `MODEL_API_KEY`. |
| Model | `muse-spark-1.3` (`META_MODEL`). Also documented: `muse-spark-1.2`, `muse-spark-1.1`, and `-contributor` variants (discounted; Meta may train on your data). |
| Output limit | `max_completion_tokens` (`max_tokens` is a deprecated alias and is not sent) |
| Temperature | 0–2 (`AI_TEMPERATURE`, default 0.2). Meta's guide suggests leaving it unset; set `AI_TEMPERATURE` to `1.0` to match the server default. |
| Reasoning | optional `reasoning_effort`: `minimal` · `low` · `medium` · `high` · `xhigh` (`META_REASONING_EFFORT`) |
| Structured output | `response_format: {"type": "json_schema", "json_schema": {"name", "schema", "strict"}}` — FORGE-0 sends the Pydantic schema of each contract with `strict: false` (`META_STRUCTURED_OUTPUT=json_schema`; `json_object` and `none` also supported) |
| Never sent | `stop`, `logit_bias`, `logprobs: true` — documented to return HTTP 400 |
| Usage | `usage.prompt_tokens`, `usage.completion_tokens` recorded per call |
| Pricing (standard) | $1.25 / 1M input, $4.25 / 1M output (`AI_PRICE_INPUT_PER_M`, `AI_PRICE_OUTPUT_PER_M`) |
| Rate limits | 3,000 RPM / 4M TPM per team for `muse-spark-1.3` standard |

Robustness built in (`backend/providers/openai_compat.py`), following Meta's
[error-handling guide](https://dev.meta.ai/docs/error-handling) (re-checked 2026-10-19):

| Situation | Behaviour |
| --- | --- |
| 429 rate limit, 503 overload | retried (max 4 attempts); `Retry-After` honoured (seconds or HTTP date, capped at 120 s) |
| 500 / 502, timeouts, connection errors | retried with exponential backoff and jitter |
| 504 server time limit | **not retried unchanged** (Meta's guidance); error suggests lowering input, `AI_MAX_TOKENS` or `META_REASONING_EFFORT` |
| 400 / 401 / 402 / 403 / 404 / 413 | never retried; the `{"error": {message, type, param, code}}` envelope is parsed into a clear message with a hint (e.g. 401 → check `META_API_KEY`) |
| 400 on `response_format` / schema | structured output downgrades `json_schema → json_object → none` and the request is repeated once per step; unrelated 400s are not masked |
| `finish_reason: length` | fails fast ("truncated at max_completion_tokens") instead of a repair round that would be truncated again |
| `content: null` with `refusal`, or `finish_reason: content_filter` | reported as such |
| Output that fails schema validation | one repair round with the validation error; then the call fails |

Schemas are sent self-contained: local `$ref`/`$defs` are inlined because Meta documents the field
only as "a JSON Schema object".

Usage accounting follows the `CompletionUsage` schema: `prompt_tokens`, `completion_tokens`,
`prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens` are recorded
per call (`model_calls` table) and per investigation. Cost estimates bill cached prompt tokens at the
cached-input rate (`AI_PRICE_CACHED_INPUT_PER_M`, $0.15/1M) and the rest at $1.25/1M input and
$4.25/1M output. Tokens consumed by a call that ultimately fails (for example output that never
validates) are still counted, because they were billed.

The API key is registered with the log redactor and is never returned by the API or sent to the
browser.

> **Not yet verified against the live service.** No Meta API key was available while building
> FORGE-0, so the request/response handling is tested against the documented contract with a mock
> HTTP transport (`backend/tests/test_meta_contract.py`, `test_providers.py`), not against `api.meta.ai`. The connectivity
> check below is the first thing to run once a key exists.

## Activation (five steps)

1. **Add the key** to the backend environment (`.env` in the repository root — git-ignored):

   ```dotenv
   META_API_KEY=your-key-here
   ```

2. **Select the provider**, either in `.env`

   ```dotenv
   AI_PROVIDER=meta
   ```

   or later at runtime in **Settings → AI provider → Meta Model API → Save**.

3. **Restart the backend** (environment variables are read at startup):

   ```powershell
   # in the backend window: Ctrl+C, then
   .venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8010
   ```

4. **Check connectivity**:

   ```powershell
   backend\.venv\Scripts\python scripts\check_meta.py               # GET /models, no tokens
   backend\.venv\Scripts\python scripts\check_meta.py --structured  # + one schema-constrained request
   ```

   or **Settings → Check connectivity / Test completion**. The top bar switches from
   `MOCK · scripted` to `meta · muse-spark-1.3`.

5. **Run a real investigation**: Dashboard → *New investigation* → pick the demo repository and a
   failing test → *Start*. The investigation header shows the real provider and the report no longer
   carries the simulated-output disclaimer. For a real evaluation run:

   ```powershell
   backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --dry-run
   backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --yes
   ```

## Other OpenAI-compatible endpoints

```dotenv
AI_PROVIDER=openai
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1    # e.g. Ollama, vLLM, a gateway
OPENAI_COMPAT_MODEL=llama3.1
OPENAI_COMPAT_API_KEY=                              # if the endpoint needs one
OPENAI_COMPAT_STRUCTURED_OUTPUT=json_object
```

## What a real model must do well

The prompts (`backend/agents/prompts.py`) ask for: competing hypotheses with priors; experiments
that follow the sandbox runtime contract (Node test runner, erasable TypeScript, files under
`test/forge-experiments/`, predictions per hypothesis); and exact search/replace edits. All model
output is validated before use — invalid experiments are recorded as *rejected before execution*
and patches that do not apply are rejected — so a weaker model degrades to "inconclusive", not to
false claims.
