# Security model

FORGE-0 treats every imported repository, every model-authored experiment and every generated
patch as **untrusted code**. Untrusted code only ever runs inside a disposable Docker container.

## Sandbox (implemented — `backend/sandbox/docker.py`)

Every test run, experiment and verification is a fresh `docker run --rm` with:

| Control | Setting |
| --- | --- |
| Network | `--network none` |
| Host filesystem | **no bind mounts**: the workspace is streamed in as a tar archive over stdin |
| Root filesystem | `--read-only` |
| Workspace | `tmpfs /work` (default 256 MB, `nosuid,nodev`) — also the disk-usage limit |
| Temp | `tmpfs /tmp` 64 MB, `noexec,nosuid,nodev` |
| User | `--user 1000:1000` (non-root) |
| Capabilities | `--cap-drop ALL`, `--security-opt no-new-privileges` |
| Privileged | never |
| CPU / memory | `--cpus 1.0`, `--memory 512m --memory-swap 512m` |
| Processes / files | `--pids-limit 128`, `--ulimit nofile=512`, `--ulimit fsize=64MB` |
| Time | `timeout -s KILL` inside the container **and** a host-side deadline followed by `docker kill` |
| Docker socket | never mounted into experiment containers |
| Environment | only `HOME`, `CI`, `NO_COLOR`, empty `NODE_OPTIONS`; no host secrets |
| Output | stdout/stderr truncated (64 KB) and passed through the secret redactor |

These properties are tested against a real Docker daemon in
`backend/tests/test_integration_docker.py` (network access fails, writes outside the workspace
fail, uid is 1000, host secrets are absent, timeouts are enforced).

## No arbitrary command execution

Models never provide shell commands. They choose an **allowlisted runner** (`node_test`, `pytest`)
and a list of test targets; `sandbox/runners.py` validates every target against a strict path
pattern (no `..`, no absolute paths, no shell metacharacters, allowed extensions only) and builds the
argv itself. The only shell involved is the fixed `sh -c "tar -x … && exec timeout … <quoted argv>"`
inside the container.

On the host, FORGE-0 executes only `docker` (or `wsl -- docker`) and `git clone`
(`core.hooksPath=/dev/null`, `protocol.file.allow=never`, https URLs only, `GIT_TERMINAL_PROMPT=0`,
minimal environment). It never runs repository scripts on the host.

## Edits and file access

* All edits target disposable copies under `DATA_DIR/workspaces`; the imported snapshot and the
  user's original repository are never modified.
* Paths are resolved with traversal and symlink-escape checks; symlinks are copied as links and never
  followed into the sandbox archive.
* Repairs may not modify test files (`*.test.*`, `*.spec.*`, `test/`, `tests/`…), so a "fix" cannot
  weaken the tests that judge it. Experiments may only *add* files.
* Local imports are restricted to `demo/` and `IMPORT_ALLOWED_ROOTS`.

## Secrets

* API keys are read only from the environment (`.env` is git-ignored; `.env.example` has no values).
* The API reports only whether a key is configured; keys never reach the browser or browser storage.
* Keys are registered with the log redactor; JSON logs mask bearer tokens, `api_key=…` patterns and
  GitHub/OpenAI-style tokens.
* CI runs gitleaks on every push.

## Authentication

`AUTH_MODE=local` (default) is for single-user localhost development: the API binds to
`127.0.0.1`. `AUTH_MODE=token` requires `Authorization: Bearer $FORGE_API_TOKEN` on every endpoint
except the health probe (SSE accepts `?token=`). Multi-user authentication is **not** implemented.

## Known limitations

* **Container isolation is not a VM.** Experiments share the host kernel; a kernel or runtime escape
  would break isolation. For hostile code, run the daemon inside a VM (WSL2 already is one) or use
  gVisor/Kata (`--runtime=runsc`) — not yet wired up.
* **Docker Compose full stack** mounts `/var/run/docker.sock` into the *backend* container so it can
  launch sandboxes. That gives the backend root-equivalent access to the Docker host. Experiment
  containers never get the socket. Prefer the host-run backend or a rootless Docker daemon.
* Prompt injection: repository content is sent to the model. A malicious repository can try to steer
  hypotheses or patches. Mitigations: patches cannot touch tests, everything is verified by
  execution, nothing is applied without a human — but a model could still be persuaded to propose a
  harmful-but-passing change, which is why human review remains mandatory.
* Dependency installation inside the sandbox is not supported (no network), so repositories must
  run with zero dependencies or ship them; this is a deliberate trade-off.
* WSL2 note: Docker 29 publishes ports via iptables without a listening socket, and the WSL relay
  drops IPv6 `::1`; FORGE-0 therefore connects to `127.0.0.1`.
