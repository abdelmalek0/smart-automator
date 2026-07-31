"""Tests for dashboard authentication, ownership, and run persistence."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from smart_automator.server import run_state
from smart_automator.server.auth.stores import SessionStore, UserStore
from smart_automator.server.run_state import RunState, add_run, get_run_for_user, list_runs_for_user
from smart_automator.storage.websites import WebsiteStore


def test_auth_setup_needs_registration(anon_client: TestClient) -> None:
    res = anon_client.get("/api/auth/setup")
    assert res.status_code == 200
    assert res.json() == {"needs_registration": True, "registration_open": True}


def test_auth_setup_registration_open_by_default(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_OPEN_REGISTER", raising=False)
    first = anon_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "password123"},
    )
    assert first.status_code == 201

    opened = anon_client.get("/api/auth/setup")
    assert opened.json() == {"needs_registration": False, "registration_open": True}

    monkeypatch.setenv("ALLOW_OPEN_REGISTER", "false")
    closed = anon_client.get("/api/auth/setup")
    assert closed.json() == {"needs_registration": False, "registration_open": False}


def test_registration_can_be_disabled(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_OPEN_REGISTER", "false")
    first = anon_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "password123"},
    )
    assert first.status_code == 201

    denied = anon_client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "password123"},
    )
    assert denied.status_code == 403


def test_register_login_logout_flow(anon_client: TestClient) -> None:
    register = anon_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "password123"},
    )
    assert register.status_code == 201
    assert register.json()["user"]["username"] == "alice"

    setup = anon_client.get("/api/auth/setup")
    assert setup.json()["needs_registration"] is False

    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"

    logout = anon_client.post("/api/auth/logout")
    assert logout.status_code == 200

    me_after = anon_client.get("/api/auth/me")
    assert me_after.status_code == 401


def test_logout_works_without_valid_session(anon_client: TestClient) -> None:
    res = anon_client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_protected_routes_require_auth(anon_client: TestClient) -> None:
    res = anon_client.get("/api/runs")
    assert res.status_code == 401


def test_registration_disabled_after_first_user(tmp_path) -> None:
    users_file = tmp_path / "users.json"
    store = UserStore(users_file)
    store.create_user("first", "password123", allow_when_users_exist=False)
    with pytest.raises(PermissionError, match="Registration is disabled"):
        store.create_user("second", "password123", allow_when_users_exist=False)


def test_corrupt_users_file_fail_closed(tmp_path) -> None:
    users_file = tmp_path / "users.json"
    users_file.write_text("{not-json", encoding="utf-8")
    store = UserStore(users_file)
    with pytest.raises(RuntimeError, match="Corrupt users file"):
        store.has_users()


def test_session_touch_is_throttled(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create_session("user-1")
    mtime_1 = (tmp_path / "sessions.json").stat().st_mtime
    time.sleep(0.02)
    assert store.get_session(session.session_id) is not None
    mtime_2 = (tmp_path / "sessions.json").stat().st_mtime
    assert mtime_2 == mtime_1


def test_run_ownership_isolation(auth_client: TestClient, second_auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/runs",
        json={
            "task": "Owner task",
            "success_criteria": "Done",
            "headless": True,
            "max_steps": 3,
        },
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    denied = second_auth_client.get(f"/api/runs/{run_id}")
    assert denied.status_code == 404

    allowed = auth_client.get(f"/api/runs/{run_id}")
    assert allowed.status_code == 200
    assert allowed.json()["run_id"] == run_id


def test_finished_run_persists_after_memory_clear(auth_client: TestClient) -> None:
    user_id = auth_client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id="persisted-run-id",
        user_id=user_id,
        task="Persist me",
        headless=True,
        max_steps=5,
        success_criteria="Saved",
        effective_task="Effective persist me",
    )
    run.status = "pass"
    run.finished_at = time.time()
    run.summary = "Saved"
    run.report_path = "/tmp/report.html"
    run.steps = [{"index": 1, "thought": "done", "status": "pass"}]
    add_run(run)
    run.persist()

    run_state._runs.clear()

    listed = auth_client.get("/api/runs")
    assert listed.status_code == 200
    ids = [item["run_id"] for item in listed.json()]
    assert "persisted-run-id" in ids

    loaded = auth_client.get("/api/runs/persisted-run-id")
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["status"] == "pass"
    assert body["summary"] == "Saved"
    assert len(body["steps"]) == 1

    rehydrated = get_run_for_user(user_id, "persisted-run-id")
    assert rehydrated is not None
    assert rehydrated.effective_task == "Effective persist me"
    assert rehydrated.report_path == "/tmp/report.html"
    assert list_runs_for_user(user_id)


def test_report_download_falls_back_after_restart(
    auth_client: TestClient, tmp_path, monkeypatch
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    monkeypatch.setattr("smart_automator.server.app.REPORT_DIR", report_dir)

    user_id = auth_client.get("/api/auth/me").json()["user"]["id"]
    run_id = "report-fallback-run"
    report_file = report_dir / f"{run_id}.html"
    report_file.write_text("<html>ok</html>", encoding="utf-8")

    run = RunState(
        run_id=run_id,
        user_id=user_id,
        task="Report me",
        headless=True,
        max_steps=5,
        success_criteria="ok",
    )
    run.status = "pass"
    run.finished_at = time.time()
    # Simulate a legacy persisted record without report_path.
    run.persist()
    run_state._runs.clear()

    res = auth_client.get(f"/api/runs/{run_id}/report")
    assert res.status_code == 200
    assert "ok" in res.text


def test_websites_are_scoped_per_user(auth_client: TestClient, second_auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/websites",
        json={"name": "Owner Site", "url": "https://owner.example"},
    )
    assert created.status_code == 201
    website_id = created.json()["id"]

    owner_list = auth_client.get("/api/websites")
    assert any(item["id"] == website_id for item in owner_list.json())

    other_list = second_auth_client.get("/api/websites")
    assert all(item["id"] != website_id for item in other_list.json())

    denied = second_auth_client.get(f"/api/websites/{website_id}")
    assert denied.status_code == 404


def test_legacy_websites_migrate_only_once(tmp_path, monkeypatch) -> None:
    websites_dir = tmp_path / "websites"
    websites_dir.mkdir()
    legacy = tmp_path / "websites.json"
    legacy.write_text(
        json.dumps(
            {
                "websites": [
                    {
                        "id": "legacy-1",
                        "name": "Legacy",
                        "url": "https://legacy.example",
                        "context_prompt": "",
                        "tasks": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", websites_dir)
    monkeypatch.setattr("smart_automator.storage.websites.WEBSITES_FILE", legacy)
    monkeypatch.setattr("smart_automator.storage.websites.server_paths.WEBSITES_DIR", websites_dir)

    first = WebsiteStore("user-a", websites_dir / "user-a.json")
    assert any(site.id == "legacy-1" for site in first.list_websites())
    assert not legacy.exists()
    assert legacy.with_suffix(".json.migrated").exists()

    second = WebsiteStore("user-b", websites_dir / "user-b.json")
    assert second.list_websites() == []
