"""Meta Model API connectivity check.

    backend/.venv/Scripts/python scripts/check_meta.py            # GET /models (no tokens used)
    backend/.venv/Scripts/python scripts/check_meta.py --deep     # also a 16-token chat completion
    backend/.venv/Scripts/python scripts/check_meta.py --structured
        # plus one structured-output request using FORGE-0's HypothesisSet schema

Reads META_API_KEY (or MODEL_API_KEY), META_API_BASE_URL and META_MODEL from the environment
or .env. The key itself is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from core.config import get_settings  # noqa: E402
from core.schemas import HypothesisSet  # noqa: E402
from providers.base import AgentRequest, ProviderError  # noqa: E402
from providers.meta import MetaModelProvider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep", action="store_true", help="send a minimal chat completion")
    parser.add_argument("--structured", action="store_true", help="send a structured-output request")
    args = parser.parse_args()

    settings = get_settings()
    if settings.resolved_meta_key is None:
        print("META_API_KEY is not set. Add it to .env (never commit it) and retry.")
        return 1
    provider = MetaModelProvider(settings)
    result = provider.check(deep=args.deep or args.structured)
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        return 1
    if args.structured:
        request = AgentRequest(
            agent="connectivity_check",
            task="hypotheses",
            system="You generate competing hypotheses for software failures.",
            user="A test expects 1 charge but sees 2 after a retried payment. Give two hypotheses.",
        )
        try:
            completion = provider.generate(request, HypothesisSet)
        except ProviderError as exc:
            print(f"Structured output failed: {exc}")
            return 1
        print(
            f"Structured output OK: {len(completion.output.hypotheses)} hypotheses, "
            f"{completion.usage.prompt_tokens}+{completion.usage.completion_tokens} tokens, "
            f"model {completion.model}, response_format={provider.structured_output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
