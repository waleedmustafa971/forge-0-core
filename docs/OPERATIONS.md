# Operations guide

How to run, measure, stop and troubleshoot FORGE-0 locally. Written for the development machine
it was built on (Windows 11, 7.7 GB RAM, Docker Engine inside WSL2 Ubuntu), but every script also
works with Docker Desktop.

## Two run modes

| | Lite mode (recommended on ≤ 8 GB RAM) | Full mode (hot reload) |
| --- | --- | --- |
| Start | `.\scripts\lite.ps1 start` | `.\scripts\dev.ps1` |
| Stop | `.\scripts\lite.ps1 stop` | `.\scripts\stop.ps1` |
| Status | `.\scripts\lite.ps1 status` | `.\scripts\measure_memory.ps1` |
| Dashboard | <http://127.0.0.1:8010> (served by the backend from `frontend/dist`) | <http://127.0.0.1:5173> (Vite) |
| API | <http://127.0.0.1:8010/api> (docs at `/docs`) | <http://127.0.0.1:8010/api> |
| Processes | one hidden, detached backend + its WSL keep-alive | backend window, frontend window, Vite, esbuild, keep-alives |
| PostgreSQL | tuned (`docker-compose.lite.yml`), capped at 256 MB | capped at 512 MB |
| Concurrency | 1 investigation, 1 sandbox container (384 MB) at a time, 3 DB connections | 2 investigations, 2 sandbox containers (512 MB each) |
| Logs | `data/logs/backend.out.log`, `data/logs/backend.err.log` | the console windows |

Lite mode rebuilds the dashboard automatically when `frontend/src` changed since the last build
(`-Rebuild` forces it). Use full mode only when editing the frontend.

Linux/macOS: `./scripts/dev.sh` (full mode; stop with Ctrl+C and `docker compose stop db`).

### Stopping everything

* `.\scripts\lite.ps1 stop` ends the backend process tree and stops the PostgreSQL container.
  Add `-ReclaimWslCache` to drop WSL's page cache so Windows gets that memory back sooner.
* `.\scripts\stop.ps1` ends the windows opened by `dev.ps1`, any stray uvicorn/Vite/esbuild process
  started from this checkout, the keep-alive and the PostgreSQL container (`-KeepDatabase` to keep it).
* Neither script touches anything outside this checkout, other projects' containers, or WSL itself.

## Memory measurements (2026-10-19)

Same workload in both modes: the double-charge investigation (D2), which ends in a verified fix.
Measured with `scripts/measure_memory.ps1` and a 2-second sampler.

| | Full mode | Lite mode |
| --- | --- | --- |
| FORGE-0 host processes | 14 · ~391 MB private (393 MB peak) | 4 · ~100–105 MB private (102 MB peak) |
| Memory in use inside the WSL VM | 817 MB (895 MB peak) | 771 MB (846 MB peak) |
| PostgreSQL container | ~30–58 MB | ~22–35 MB |

Where the host memory actually goes on this machine: Chrome (~1.5 GB), VS Code, Brave, Claude Code
and the WSL VM. The VM reserves up to its `.wslconfig` cap (3 GB) and keeps freed memory as page
cache; image builds can leave ~2 GB cached. `lite.ps1 stop -ReclaimWslCache` releases it.

**Not changed (needs explicit approval because it is global):** lowering `memory=3GB` to `2GB` and
setting `autoMemoryReclaim=dropCache` in `%USERPROFILE%\.wslconfig` would cap WSL further. The
FORGE-0 workload fits comfortably in 2 GB; other projects using the same distro may not.

## WSL-specific behaviour (and how FORGE-0 handles it)

| Behaviour | Handling |
| --- | --- |
| WSL stops an idle distro (and dockerd and all containers) when no `wsl.exe` session is attached | The backend holds a keep-alive session for its lifetime. It runs `cat` on a pipe owned by the backend, so it exits by itself when the backend dies, even on a hard kill. |
| A stopped distro takes PostgreSQL with it | On startup the backend waits up to 90 s for the database; `restart: unless-stopped` brings the container back once WSL wakes. |
| Docker 29 publishes ports via iptables, and the WSL relay drops IPv6 `::1` | All URLs use `127.0.0.1`, never `localhost`; the database connection has a 10 s timeout. |
| Ports 8000 and 8080 are relayed for another project's containers | FORGE-0 uses 8010 (API), 5173 (Vite), 5433 (PostgreSQL), 8090 (Compose UI). |
| Compose `env_file` reads `VAR=   # comment` as the value | `.env.example` keeps comments on their own lines. |
| `Start-Process` children inherit the caller's pipes | `lite.ps1` creates the backend through WMI (`Win32_Process.Create`), fully detached. |

## Verifying the demo

```powershell
.\scripts\lite.ps1 start
backend\.venv\Scripts\python scripts\audit_demo.py
```

`audit_demo.py` runs the double-charge investigation through the public API and checks 17 things.
It confirms the failure is reproduced, the first (regression-causing) patch is rejected, the revised
patch is verified, every decision appears in the evidence timeline, the Markdown report exports, and
mock output is labelled as simulated. It exits non-zero if any check fails.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `lite.ps1 start` says the backend did not become healthy | `data/logs/backend.err.log`; usually PostgreSQL is not reachable. Run `wsl -- docker ps`. |
| "Port 8010 is in use" | Another FORGE-0 backend (full mode?). Run `.\scripts\stop.ps1` or `.\scripts\lite.ps1 stop`. |
| Containers vanish between commands | Nothing holds a WSL session. Start FORGE-0 through the scripts, which keep one open. |
| Sandbox unavailable in `/api/system/health` | `wsl -- docker version`; the first call after WSL starts can take ~10 s. |
| Investigations stuck in "running" after a crash | They are marked failed automatically on the next backend start. |
