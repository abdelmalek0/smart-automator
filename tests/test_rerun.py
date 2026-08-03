"""Tests for re-run support (run config in API responses)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from smart_automator.server.app import app


def test_run_summary_includes_config(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={
            "task": "Smoke test",
            "success_criteria": "Page loads successfully",
            "headless": True,
            "max_steps": 25,
            "cdp_url": "ws://localhost:9222",
            "fresh_profile": True,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["headless"] is True
    assert body["max_steps"] == 25
    assert body["cdp_url"] == "ws://localhost:9222"
    assert body["fresh_profile"] is True
    assert body["success_criteria"] == "Page loads successfully"

    run_id = body["run_id"]
    get_res = client.get(f"/api/runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["headless"] is True
