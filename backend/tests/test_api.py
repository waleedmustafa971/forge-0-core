"""REST API tests (background jobs are replaced by an in-process run with the fake sandbox)."""

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import Orchestrator
from api.main import create_app
from api.routes import investigations as inv_routes
from tests.fakes import TARGET, FakeSandbox


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def run_inline(monkeypatch):
    monkeypatch.setattr(
        inv_routes, "start_investigation", lambda inv_id: Orchestrator(inv_id, sandbox=FakeSandbox()).run()
    )


def demo_repo(client):
    repos = client.get("/api/repositories").json()
    return next(r for r in repos if r["source_type"] == "demo")


def test_health_reports_components(client):
    body = client.get("/api/system/health").json()
    assert body["database"]["ok"] is True
    assert body["provider"]["active"] == "mock" and body["provider"]["simulated"] is True
    assert "sandbox" in body


def test_demo_repository_is_seeded_with_profile(client):
    repo = demo_repo(client)
    assert repo["profile"]["runtime"]["runner"] == "node_test"
    assert repo["profile"]["languages"]["TypeScript"] >= 10
    files = [f["path"] for f in client.get(f"/api/repositories/{repo['id']}/tree").json()["files"]]
    assert "src/services/orderService.ts" in files
    content = client.get(
        f"/api/repositories/{repo['id']}/file", params={"path": "src/domain/status.ts"}
    ).json()
    assert "canTransition" in content["content"]


def test_file_endpoint_blocks_traversal(client):
    repo = demo_repo(client)
    response = client.get(f"/api/repositories/{repo['id']}/file", params={"path": "../../../pyproject.toml"})
    assert response.status_code == 400


def test_local_import_restricted_to_allowed_roots(client, tmp_path):
    response = client.post("/api/repositories", json={"source_type": "local", "path": str(tmp_path)})
    assert response.status_code == 400
    assert "restricted" in response.json()["detail"]


def test_git_import_requires_https(client):
    response = client.post("/api/repositories", json={"source_type": "git", "url": "file:///etc"})
    assert response.status_code == 400


def test_settings_never_expose_secrets(client):
    body = client.get("/api/settings").json()
    assert body["secrets"] == {"meta_api_key_configured": False, "openai_compat_api_key_configured": False}
    assert "key" not in str(body["runtime"]).lower()
    updated = client.put("/api/settings", json={"temperature": 0.7, "max_experiments": 5}).json()
    assert updated["temperature"] == 0.7 and updated["max_experiments"] == 5
    assert client.put("/api/settings", json={"temperature": 9}).status_code == 422
    reset = client.post("/api/settings/reset").json()
    assert reset["temperature"] == 0.2


def test_provider_check_meta_without_key(client):
    body = client.post("/api/system/provider/check", json={"provider": "meta"}).json()
    assert body["ok"] is False
    assert body["provider"] == "mock" and body["fallback_reason"]


def test_investigation_lifecycle_and_report(client, run_inline):
    repo = demo_repo(client)
    created = client.post(
        "/api/investigations",
        json={"repository_id": repo["id"], "target_test": TARGET, "symptom": "cancelled orders ship"},
    )
    assert created.status_code == 202
    inv_id = created.json()["id"]

    detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["status"] == "completed" and detail["verdict"] == "verified_fix"
    assert detail["counts"]["hypotheses"] == 3

    events = client.get(f"/api/investigations/{inv_id}/events").json()
    assert events[0]["type"] == "queued" and events[-1]["type"] == "completed"
    later = client.get(f"/api/investigations/{inv_id}/events", params={"after": events[-2]["id"]}).json()
    assert [e["id"] for e in later] == [events[-1]["id"]]

    with client.stream("GET", f"/api/investigations/{inv_id}/events/stream") as stream:
        text = "".join(stream.iter_text())
    assert "event: forge" in text and "event: end" in text

    hyps = client.get(f"/api/investigations/{inv_id}/hypotheses").json()
    assert hyps[0]["status"] == "confirmed" and hyps[0]["rank"] == 1
    exps = client.get(f"/api/investigations/{inv_id}/experiments").json()
    assert len(exps) == 4
    patches = client.get(f"/api/investigations/{inv_id}/patches").json()
    patch = patches[0]
    assert patch["status"] == "verified"

    diff = client.get(f"/api/investigations/{inv_id}/patches/{patch['id']}/diff")
    assert diff.headers["content-type"].startswith("text/x-diff")
    assert "+++ b/src/domain/status.ts" in diff.text

    review = client.post(
        f"/api/investigations/{inv_id}/patches/{patch['id']}/review", json={"decision": "approved"}
    )
    assert review.json()["review_status"] == "approved"

    report = client.get(f"/api/investigations/{inv_id}/report").json()
    assert report["provider"]["simulated"] is True and report["provider"]["disclaimer"]
    assert report["proposed_fix"] == "P1"
    assert {h["key"] for h in report["rejected_hypotheses"]} == {"H2", "H3"}
    markdown = client.get(f"/api/investigations/{inv_id}/report", params={"format": "md"}).text
    assert "SIMULATED" in markdown and "```diff" in markdown

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["verified_repairs"] >= 1

    assert client.delete(f"/api/investigations/{inv_id}").status_code == 204
    assert client.get(f"/api/investigations/{inv_id}").status_code == 404


def test_rejected_patch_cannot_be_approved(client, monkeypatch):
    monkeypatch.setattr(
        inv_routes,
        "start_investigation",
        lambda inv_id: Orchestrator(inv_id, sandbox=FakeSandbox(break_regression=True)).run(),
    )
    repo = demo_repo(client)
    inv_id = client.post(
        "/api/investigations", json={"repository_id": repo["id"], "target_test": TARGET}
    ).json()["id"]
    patch = client.get(f"/api/investigations/{inv_id}/patches").json()[0]
    assert patch["status"] == "rejected"
    response = client.post(
        f"/api/investigations/{inv_id}/patches/{patch['id']}/review", json={"decision": "approved"}
    )
    assert response.status_code == 409


def test_token_auth_mode(monkeypatch):
    from pydantic import SecretStr

    from core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "token")
    monkeypatch.setattr(settings, "forge_api_token", SecretStr("t0ken-value"))
    with TestClient(create_app()) as c:
        assert c.get("/api/repositories").status_code == 401
        assert c.get("/api/repositories", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/repositories", headers={"Authorization": "Bearer t0ken-value"}).status_code == 200
        assert c.get("/api/system/health").status_code == 200  # health stays public for probes


def test_deleting_a_repository_removes_its_investigations(client, run_inline, tmp_path, monkeypatch):
    from core.config import get_settings

    source = tmp_path / "svc"
    source.mkdir()
    (source / "package.json").write_text('{"name": "svc", "scripts": {"test": "node --test"}}')
    monkeypatch.setattr(get_settings(), "import_allowed_roots", str(tmp_path))
    repo = client.post("/api/repositories", json={"source_type": "local", "path": str(source)}).json()
    inv = client.post("/api/investigations", json={"repository_id": repo["id"]}).json()
    assert client.delete(f"/api/repositories/{repo['id']}").status_code == 204
    assert client.get(f"/api/repositories/{repo['id']}").status_code == 404
    assert client.get(f"/api/investigations/{inv['id']}").status_code == 404


def test_lite_mode_serves_dashboard_with_spa_fallback(tmp_path, monkeypatch):
    from core.config import get_settings

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>FORGE-0</title>")
    (dist / "assets" / "app.js").write_text("console.log('x')")
    (tmp_path / "secret.txt").write_text("outside")
    monkeypatch.setattr(get_settings(), "serve_frontend_dir", str(dist))
    with TestClient(create_app()) as c:
        assert "FORGE-0" in c.get("/").text
        assert "FORGE-0" in c.get("/investigations/abc/report").text  # client-side route
        assert c.get("/assets/app.js").text == "console.log('x')"
        assert "outside" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/does-not-exist").status_code == 404
        assert c.get("/api/system/health").json()["status"] == "ok"


def test_wait_for_database_retries_until_reachable(monkeypatch):
    from sqlalchemy.exc import OperationalError

    import core.database as database

    calls = {"n": 0}
    real_get_engine = database.get_engine

    class FlakyEngine:
        def connect(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OperationalError("SELECT 1", {}, Exception("connection timeout expired"))
            return real_get_engine().connect()

    monkeypatch.setattr(database, "get_engine", lambda: FlakyEngine())
    database.wait_for_database(timeout_s=5, interval_s=0.01)
    assert calls["n"] == 3

    calls["n"] = -100
    with pytest.raises(OperationalError):
        database.wait_for_database(timeout_s=0.05, interval_s=0.01)
