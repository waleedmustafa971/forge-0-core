"""Docker-isolated execution of experiments.

Security properties of every experiment container:

* no network (``--network none``), no host Docker socket, no bind mounts of host paths;
* read-only root filesystem; the workspace is streamed in as a tar archive over stdin and
  unpacked into a size-limited tmpfs (``/work``), so nothing is written back to the host;
* non-root user, all Linux capabilities dropped, ``no-new-privileges``;
* CPU, memory (no swap), PID and open-file limits; a hard timeout enforced both inside the
  container (``timeout -s KILL``) and from the host (``docker kill``);
* only allowlisted runners (see :mod:`sandbox.runners`) — never model-authored shell.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings, get_settings
from core.logging import redact_known
from core.schemas import ExecutionResult
from sandbox.runners import Runner, get_runner
from sandbox.tap import parse_tap

log = logging.getLogger(__name__)

EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist", "build"}
MAX_FILE_BYTES = 2_000_000


class SandboxUnavailableError(RuntimeError):
    pass


def resolve_docker_command(settings: Settings) -> list[str]:
    configured = settings.sandbox_docker_command.strip()
    if configured and configured != "auto":
        return configured.split()
    if shutil.which("docker"):
        return ["docker"]
    if platform.system() == "Windows" and shutil.which("wsl"):
        distro = ["-d", settings.sandbox_wsl_distro] if settings.sandbox_wsl_distro else []
        return ["wsl", *distro, "--", "docker"]
    return ["docker"]


def build_workspace_tar(root: Path, max_bytes: int) -> bytes:
    """Archives `root` (excluding VCS/dependency dirs and symlinks) into an in-memory tar."""
    buffer = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in EXCLUDED_DIRS and not Path(dirpath, d).is_symlink()
            ]
            for filename in filenames:
                path = Path(dirpath, filename)
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    continue
                total += size
                if total > max_bytes:
                    raise ValueError(f"Workspace exceeds sandbox upload limit of {max_bytes} bytes")
                arcname = path.relative_to(root).as_posix()
                info = tarfile.TarInfo(arcname)
                info.size = size
                info.mode = 0o644
                info.mtime = int(path.stat().st_mtime)
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
    return buffer.getvalue()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n... [{len(text) - limit} characters truncated] ...\n{tail}", True


@dataclass
class SandboxStatus:
    available: bool
    detail: str
    docker_command: list[str]
    server_version: str | None = None


class DockerSandbox:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.docker = resolve_docker_command(self.settings)
        self._status: SandboxStatus | None = None
        self._status_at = 0.0
        self._lock = threading.Lock()
        self._images_ready: set[str] = set()
        # Bounds concurrent experiment containers across all investigations and scans.
        self._slots = threading.BoundedSemaphore(max(1, self.settings.sandbox_max_concurrent))

    # -- availability -------------------------------------------------------
    def status(self, refresh: bool = False) -> SandboxStatus:
        with self._lock:
            if not refresh and self._status and time.monotonic() - self._status_at < 30:
                return self._status
            try:
                proc = subprocess.run(
                    [*self.docker, "version", "--format", "{{.Server.Version}}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    status = SandboxStatus(True, "docker daemon reachable", self.docker, proc.stdout.strip())
                else:
                    status = SandboxStatus(False, (proc.stderr or proc.stdout).strip()[:300], self.docker)
            except (OSError, subprocess.TimeoutExpired) as exc:
                status = SandboxStatus(False, f"docker not reachable: {exc}", self.docker)
            self._status, self._status_at = status, time.monotonic()
            return status

    def ensure_image(self, image: str) -> None:
        if image in self._images_ready:
            return
        inspect = subprocess.run(
            [*self.docker, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if inspect.returncode != 0:
            log.info("pulling sandbox image", extra={"image": image})
            pull = subprocess.run([*self.docker, "pull", image], capture_output=True, text=True, timeout=600)
            if pull.returncode != 0:
                raise SandboxUnavailableError(
                    f"Cannot pull sandbox image {image}: {pull.stderr.strip()[:300]}"
                )
        self._images_ready.add(image)

    # -- execution ----------------------------------------------------------
    def container_args(self, name: str, image: str, script: str) -> list[str]:
        s = self.settings
        return [
            *self.docker,
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            "forge0.role=experiment",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/work:rw,exec,nosuid,nodev,size={s.sandbox_workdir_size},mode=1777",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",  # noqa: S108 - private tmpfs inside the container
            "--cpus",
            str(s.sandbox_cpus),
            "--memory",
            s.sandbox_memory,
            "--memory-swap",
            s.sandbox_memory,
            "--pids-limit",
            str(s.sandbox_pids_limit),
            "--ulimit",
            "nofile=512:512",
            "--ulimit",
            "fsize=67108864",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "1000:1000",
            "--workdir",
            "/work",
            "--env",
            "HOME=/tmp",
            "--env",
            "CI=1",
            "--env",
            "NODE_OPTIONS=",
            "--env",
            "NO_COLOR=1",
            image,
            "sh",
            "-c",
            script,
        ]

    def run_tests(
        self,
        workspace: Path,
        runner_name: str,
        targets: list[str],
        test_name_pattern: str | None = None,
        timeout_s: int | None = None,
    ) -> ExecutionResult:
        runner: Runner = get_runner(runner_name)
        argv = runner.argv(targets, test_name_pattern)
        timeout = int(timeout_s or self.settings.sandbox_timeout_s)
        image = runner.image()
        sandbox_meta: dict[str, str | int | float | bool] = {
            "network": "none",
            "read_only_rootfs": True,
            "cpus": self.settings.sandbox_cpus,
            "memory": self.settings.sandbox_memory,
            "pids_limit": self.settings.sandbox_pids_limit,
            "workdir_tmpfs": self.settings.sandbox_workdir_size,
            "timeout_s": timeout,
            "user": "1000:1000",
        }
        started = time.monotonic()

        def failure(message: str) -> ExecutionResult:
            return ExecutionResult(
                runner=runner.name,
                image=image,
                command=argv,
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                infra_error=message,
                sandbox=sandbox_meta,
            )

        status = self.status()
        if not status.available:
            return failure(f"Sandbox unavailable: {status.detail}")
        try:
            self.ensure_image(image)
            payload = build_workspace_tar(workspace, self.settings.sandbox_max_upload_bytes)
        except (SandboxUnavailableError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
            return failure(str(exc))

        name = f"forge0-exp-{uuid.uuid4().hex[:12]}"
        sandbox_meta["container"] = name
        args = self.container_args(name, image, runner.shell_script(argv, timeout))
        timed_out = False
        with self._slots:
            try:
                proc = subprocess.run(args, input=payload, capture_output=True, timeout=timeout + 30)
                exit_code: int | None = proc.returncode
                stdout_b, stderr_b = proc.stdout, proc.stderr
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                exit_code = None
                stdout_b, stderr_b = exc.stdout or b"", exc.stderr or b""
                subprocess.run([*self.docker, "kill", name], capture_output=True, timeout=30)
        duration_ms = int((time.monotonic() - started) * 1000)
        if exit_code == 137:
            timed_out = True
        stdout = redact_known(stdout_b.decode("utf-8", errors="replace"))
        stderr = redact_known(stderr_b.decode("utf-8", errors="replace"))
        infra_error = None
        if exit_code == 125 or (exit_code is not None and "docker: Error" in stderr[:400]):
            infra_error = stderr.strip()[:500] or "docker run failed"
        test_run = parse_tap(stdout) if runner.name == "node_test" else None
        limit = self.settings.sandbox_max_output_bytes
        stdout_t, stdout_cut = _truncate(stdout, limit)
        stderr_t, stderr_cut = _truncate(stderr, limit // 2)
        return ExecutionResult(
            runner=runner.name,
            image=image,
            command=argv,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
            stdout=stdout_t,
            stderr=stderr_t,
            stdout_truncated=stdout_cut,
            stderr_truncated=stderr_cut,
            infra_error=infra_error,
            sandbox=sandbox_meta,
            test_run=test_run,
        )


class WslKeepAlive:
    """Holds a WSL session open while the backend runs.

    WSL stops an idle distro (and with it dockerd and every container) once no wsl.exe
    session is attached. When the sandbox reaches Docker through `wsl`, one idle session
    keeps the daemon available for the backend's lifetime.

    The session runs `cat` on a pipe held by this process, so it ends by itself when the
    backend exits for any reason (including a hard kill): the OS closes the pipe and `cat`
    sees EOF. A `sleep infinity` session would be orphaned instead.
    """

    def __init__(self, docker_command: list[str]) -> None:
        self.command = docker_command
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> bool:
        if not self.command or self.command[0].lower() not in ("wsl", "wsl.exe"):
            return False
        prefix = self.command[: self.command.index("--")] if "--" in self.command else ["wsl"]
        try:
            self.proc = subprocess.Popen(
                [*prefix, "--", "sh", "-c", "cat > /dev/null"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            log.warning("could not start WSL keep-alive", extra={"error": str(exc)})
            return False
        log.info("WSL keep-alive started", extra={"pid": self.proc.pid})
        return True

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            if self.proc.stdin:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        self.proc = None


_sandbox: DockerSandbox | None = None


def get_sandbox() -> DockerSandbox:
    global _sandbox
    if _sandbox is None:
        _sandbox = DockerSandbox()
    return _sandbox


def set_sandbox(sandbox: DockerSandbox | None) -> None:
    """Test hook: replace the process-wide sandbox."""
    global _sandbox
    _sandbox = sandbox
