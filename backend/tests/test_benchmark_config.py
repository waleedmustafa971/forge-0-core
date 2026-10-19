"""Benchmark harness configuration (no execution)."""

import argparse
import importlib.util
from types import SimpleNamespace

import pytest

from core.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("run_benchmark", REPO_ROOT / "benchmarks" / "run_benchmark.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
CONFIGS = REPO_ROOT / "benchmarks" / "configs"


def args(config, **overrides):
    base = {"config": config, "provider": None, "defects": "", "systems": "", "repeats": None}
    return argparse.Namespace(**{**base, **overrides})


def test_real_model_config_requires_a_real_provider():
    config = bench.load_config(args(CONFIGS / "muse-spark-1.3.json"))
    assert config["provider"] == "meta" and config["model"] == "muse-spark-1.3"
    assert config["require_real_provider"] is True
    assert config["repeats"] >= 3
    assert config["systems"] == ["baseline", "forge"] and config["defects"] == []  # all five defects


def test_mock_config_is_marked_as_not_real():
    config = bench.load_config(args(CONFIGS / "mock.json"))
    assert config["provider"] == "mock" and config["require_real_provider"] is False


def test_cli_overrides_and_validation():
    config = bench.load_config(
        args(CONFIGS / "mock.json", defects="D1-lost-update", repeats=2, systems="forge")
    )
    assert (config["defects"], config["repeats"], config["systems"]) == (["D1-lost-update"], 2, ["forge"])
    with pytest.raises(SystemExit):
        bench.load_config(args(CONFIGS / "mock.json", systems="nonsense"))


def test_worst_case_cost_for_muse_spark_config_stays_under_its_cap():
    config = bench.load_config(args(CONFIGS / "muse-spark-1.3.json"))
    runtime = SimpleNamespace(
        max_model_calls=config["budgets"]["max_model_calls"], max_tokens=config["max_tokens"]
    )
    pricing = SimpleNamespace(ai_price_input_per_m=1.25, ai_price_output_per_m=4.25)
    estimate = bench.worst_case_cost(config, 5, runtime, pricing)
    # (1 baseline + 16 forge calls) x 5 defects x 3 repeats, two requests each
    assert estimate["model_calls"] == 255 and estimate["requests"] == 510
    assert estimate["usd"] == pytest.approx(510 * 10_000 / 1e6 * 1.25 + 510 * 8192 / 1e6 * 4.25, abs=0.01)
    assert estimate["usd"] <= config["max_estimated_cost_usd"]
