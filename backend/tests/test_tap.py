from sandbox.tap import find_test, parse_tap

SAMPLE = """TAP version 13
# Subtest: fulfillment
    # Subtest: ships every item of a paid order
    ok 1 - ships every item of a paid order
      ---
      duration_ms: 285.0913
      type: 'test'
      ...
    # Subtest: reports carrier failures
    not ok 2 - reports carrier failures
      ---
      duration_ms: 206.6769
      type: 'test'
      location: '/work/test/fulfillment.test.ts:27:3'
      failureType: 'testCodeFailure'
      error: |-
        Expected values to be strictly equal:

        3 !== 5
      code: 'ERR_ASSERTION'
      name: 'AssertionError'
      stack: |-
        TestContext.<anonymous> (file:///work/test/fulfillment.test.ts:33:13)
        async Test.run (node:internal/test_runner/test:1389:7)
      ...
    # Subtest: skipped one
    ok 3 - skipped one # SKIP not today
      ---
      duration_ms: 0.1
      type: 'test'
      ...
    1..3
not ok 1 - fulfillment
  ---
  duration_ms: 627.3814
  type: 'suite'
  failureType: 'subtestsFailed'
  error: '1 subtest failed'
  ...
# Subtest: top level test
ok 2 - top level test
  ---
  duration_ms: 1
  type: 'test'
  ...
1..2
# tests 4
# pass 2
# fail 1
"""


def test_parses_nested_tests_and_skips_suites():
    run = parse_tap(SAMPLE)
    assert run.parse_ok
    assert [t.name for t in run.tests] == [
        "fulfillment > ships every item of a paid order",
        "fulfillment > reports carrier failures",
        "fulfillment > skipped one",
        "top level test",
    ]
    assert (run.total, run.passed, run.failed, run.skipped) == (4, 2, 1, 1)


def test_extracts_failure_diagnostics():
    failing = parse_tap(SAMPLE).failing()[0]
    assert failing.file == "test/fulfillment.test.ts"
    assert failing.error_name == "AssertionError"
    assert failing.failure_type == "testCodeFailure"
    assert "3 !== 5" in (failing.error or "")
    assert "fulfillment.test.ts:33:13" in (failing.stack or "")
    assert failing.duration_ms == 206.6769


def test_find_test_by_full_or_leaf_name():
    run = parse_tap(SAMPLE)
    assert find_test(run, "fulfillment > reports carrier failures") is not None
    assert find_test(run, "reports carrier failures") is not None
    assert find_test(run, "does not exist") is None


def test_empty_output_is_not_parse_ok():
    run = parse_tap("node: bad option\n")
    assert not run.parse_ok
    assert run.total == 0
