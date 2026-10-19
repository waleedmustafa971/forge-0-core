import pytest

from core.config import get_settings
from sandbox.docker import DockerSandbox, build_workspace_tar
from sandbox.runners import RunnerValidationError, get_runner


def test_node_runner_argv_is_allowlisted():
    argv = get_runner("node_test").argv(["test/**/*.test.ts"], "^does it work$")
    assert argv[:3] == ["node", "--test", "--test-reporter=tap"]
    assert "--test-name-pattern=^does it work$" in argv


@pytest.mark.parametrize(
    "target",
    [
        "../etc/passwd",
        "test/x.ts; rm -rf /",
        "$(whoami).ts",
        "test/`id`.ts",
        "/abs/path.ts",
        "test/a.sh",
        "a b.ts",
    ],
)
def test_runner_rejects_unsafe_targets(target):
    with pytest.raises(RunnerValidationError):
        get_runner("node_test").argv([target])


def test_unknown_runner_rejected():
    with pytest.raises(RunnerValidationError):
        get_runner("bash")


def test_shell_script_quotes_arguments():
    runner = get_runner("node_test")
    script = runner.shell_script(runner.argv(["test/a.test.ts"], "it's"), 30)
    assert script.startswith("tar -xf - -C /work && cd /work && exec timeout -s KILL 30 ")
    assert "'--test-name-pattern=it'\"'\"'s'" in script


def test_container_args_enforce_isolation():
    sandbox = DockerSandbox(get_settings())
    args = sandbox.container_args("forge0-exp-x", "node:24-alpine", "true")
    joined = " ".join(args)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--user 1000:1000",
        "--rm",
    ):
        assert flag in joined
    assert "docker.sock" not in joined
    assert "-v" not in args and "--volume" not in args and "--mount" not in args
    assert "--privileged" not in args


def test_workspace_tar_skips_dependencies(demo_copy):
    (demo_copy / "node_modules" / "pkg").mkdir(parents=True)
    (demo_copy / "node_modules" / "pkg" / "index.js").write_text("x")
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(build_workspace_tar(demo_copy, 10_000_000))) as archive:
        names = archive.getnames()
    assert "src/app.ts" in names
    assert not any(n.startswith("node_modules") for n in names)
    with pytest.raises(ValueError):
        build_workspace_tar(demo_copy, 10)


def test_sandbox_limits_concurrent_containers(monkeypatch, demo_copy):
    import subprocess
    import threading
    import time as _time

    from core.config import Settings
    from sandbox.docker import SandboxStatus

    sandbox = DockerSandbox(Settings(sandbox_max_concurrent=1))
    monkeypatch.setattr(sandbox, "status", lambda refresh=False: SandboxStatus(True, "ok", ["docker"], "x"))
    monkeypatch.setattr(sandbox, "ensure_image", lambda image: None)
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake_run(args, **kwargs):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        _time.sleep(0.2)
        with lock:
            active["now"] -= 1
        return subprocess.CompletedProcess(args, 0, b"TAP version 13\n1..0\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    threads = [
        threading.Thread(target=sandbox.run_tests, args=(demo_copy, "node_test", ["test/a.test.ts"]))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["peak"] == 1
