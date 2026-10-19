"""Audits the double-charge demonstration against a running FORGE-0 instance.

    backend/.venv/Scripts/python scripts/audit_demo.py [--api http://127.0.0.1:8010]

Starts the D2 investigation through the public API and checks that: the failure is reproduced,
the first (regression-causing) patch is rejected, the revised patch passes independent
verification, every decision appears in the evidence timeline, the Markdown report exports, and
simulated output is labelled as such. Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

TARGET = "payment capture > charges the customer exactly once when a timed-out request is retried"
REGRESSION = "payment capture > records separate charges for separate capture calls"


def call(api: str, path: str, body: dict | None = None, raw: bool = False):
    if not api.startswith(("http://", "https://")):
        raise SystemExit("--api must be an http(s) URL")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - scheme validated above
        f"{api}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - local API URL
        text = resp.read().decode("utf-8")
    return text if raw else json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    api = args.api.rstrip("/")

    repo = next(r for r in call(api, "/api/repositories") if r["source_type"] == "demo")
    inv = call(
        api,
        "/api/investigations",
        {
            "repository_id": repo["id"],
            "target_test": TARGET,
            "symptom": "Customers charged twice after timeouts",
        },
    )
    inv_id = inv["id"]
    print(f"investigation {inv_id} started")
    deadline = time.time() + args.timeout
    while True:
        detail = call(api, f"/api/investigations/{inv_id}")
        if detail["status"] in ("completed", "failed", "cancelled"):
            break
        if time.time() > deadline:
            print("timed out waiting for the investigation")
            return 1
        time.sleep(2)

    experiments = call(api, f"/api/investigations/{inv_id}/experiments")
    patches = call(api, f"/api/investigations/{inv_id}/patches")
    events = call(api, f"/api/investigations/{inv_id}/events")
    report = call(api, f"/api/investigations/{inv_id}/report")
    markdown = call(api, f"/api/investigations/{inv_id}/report?format=md", raw=True)
    types = [e["type"] for e in events]
    decisions = [d["message"] for d in report["decisions"]]
    p1 = patches[0] if patches else {}
    p2 = patches[1] if len(patches) > 1 else {}

    checks = [
        (
            "investigation completed with a verified fix",
            detail["status"] == "completed" and detail["verdict"] == "verified_fix",
        ),
        (
            "initial bug reproduced in isolation (E0 fails)",
            experiments[0]["key"] == "E0"
            and experiments[0]["outcome"] == "fail"
            and detail["investigation_report"]["reproduction_confirmed"],
        ),
        (
            "discriminating experiments executed",
            sum(e["designed_by"] != "investigator" for e in experiments) >= 2,
        ),
        ("first patch rejected by the verifier", p1.get("status") == "rejected"),
        (
            "rejection cites the regression",
            REGRESSION in (p1.get("verification") or {}).get("regressions", []),
        ),
        (
            "revised patch verified",
            p2.get("status") == "verified" and (p2.get("verification") or {}).get("regressions") == [],
        ),
        ("revised patch is a different change", p1.get("diff") != p2.get("diff")),
        ("timeline: experiment results recorded", types.count("experiment_result") >= 3),
        ("timeline: belief updates recorded", "belief_update" in types),
        ("timeline: both verifications recorded", types.count("verification") == 2),
        ("timeline: rejection decision recorded", any("P1 rejected" in m for m in decisions)),
        (
            "report timeline has both verifications",
            [d["type"] for d in report["decisions"]].count("verification") == 2,
        ),
        (
            "report timeline has every experiment result",
            [d["type"] for d in report["decisions"]].count("experiment_result")
            == types.count("experiment_result"),
        ),
        (
            "Markdown report exports with diff",
            markdown.startswith("# FORGE-0 Evidence Report") and "```diff" in markdown,
        ),
        (
            "Markdown report includes the evidence timeline",
            "## Evidence timeline" in markdown and "P1: REJECTED" in markdown and "P2: VERIFIED" in markdown,
        ),
        ("simulated output labelled (API)", detail["simulated"] is True and detail["provider"] == "mock"),
        (
            "simulated output labelled (report)",
            bool(report["provider"]["disclaimer"]) and "SIMULATED" in markdown,
        ),
    ]
    width = max(len(name) for name, _ in checks)
    failed = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}")
        failed += not ok
    print(f"{len(checks) - failed}/{len(checks)} checks passed - {api}/investigations/{inv_id}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
