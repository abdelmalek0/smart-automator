"""Tests for GET/PUT /api/runs/{run_id}/replay."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from smart_automator.server import replay_store
from smart_automator.server.run_state import RunState, add_run


def _add_passed_run(client: TestClient, run_id: str = "replay-edit-run") -> str:
    user_id = client.get("/api/auth/me").json()["user"]["id"]
    run = RunState(
        run_id=run_id,
        user_id=user_id,
        task="Open home",
        headless=True,
        max_steps=5,
        success_criteria="Home loads",
    )
    run.status = "pass"
    run.finished_at = time.time()
    add_run(run)
    run.persist()
    return run_id


def test_get_replay_returns_steps(client: TestClient) -> None:
    run_id = _add_passed_run(client)
    steps = [{"index": 1, "action": "go_to_url", "args": {"url": "https://example.com"}}]
    replay_store.save_run_replay(run_id, steps, "# old script")

    res = client.get(f"/api/runs/{run_id}/replay")
    assert res.status_code == 200
    body = res.json()
    assert body["replay_steps"] == steps
    assert body["replay_script"] == "# old script"


def test_get_replay_404_when_missing(client: TestClient) -> None:
    run_id = _add_passed_run(client, "no-replay-run")
    res = client.get(f"/api/runs/{run_id}/replay")
    assert res.status_code == 404


def test_put_replay_reindexes_and_regenerates_script(client: TestClient) -> None:
    run_id = _add_passed_run(client, "put-replay-run")
    replay_store.save_run_replay(
        run_id,
        [{"index": 1, "action": "wait", "args": {"seconds": 1}}],
        "# old",
    )

    payload = {
        "replay_steps": [
            {"action": "go_to_url", "args": {"url": "https://example.com"}},
            {"index": 99, "action": "wait", "args": {"seconds": 2}},
        ]
    }
    res = client.put(f"/api/runs/{run_id}/replay", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert [s["index"] for s in body["replay_steps"]] == [1, 2]
    assert body["replay_steps"][0]["action"] == "go_to_url"
    assert "go_to_url" in body["replay_script"] or "goto" in body["replay_script"]
    assert "wait" in body["replay_script"]

    loaded = replay_store.load_run_replay(run_id)
    assert loaded is not None
    assert loaded["replay_steps"] == body["replay_steps"]
    assert loaded["replay_script"] == body["replay_script"]


def test_put_replay_rejects_invalid_step(client: TestClient) -> None:
    run_id = _add_passed_run(client, "bad-replay-run")
    replay_store.save_run_replay(run_id, [], "# empty")
    res = client.put(
        f"/api/runs/{run_id}/replay",
        json={"replay_steps": [{"args": {}}]},
    )
    assert res.status_code == 400
