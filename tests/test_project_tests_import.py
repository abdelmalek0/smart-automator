from fastapi.testclient import TestClient

PACK = {
    "version": 1,
    "kind": "smart-automator.project-tests",
    "tests": [
        {
            "name": "Login",
            "task": "Open /login and sign in",
            "success_criteria": "Dashboard is visible",
        },
        {
            "task": "Open settings",
            "success_criteria": "Settings page loads",
        },
    ],
}


def test_import_appends_tests_with_new_ids(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    existing = client.post(
        f"/api/websites/{website['id']}/tasks",
        json={
            "name": "Existing",
            "task": "Already here",
            "success_criteria": "Still here",
        },
    ).json()

    res = client.post(f"/api/websites/{website['id']}/tasks/import", json=PACK)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == website["id"]
    assert len(body["tasks"]) == 3

    by_name = {t.get("name"): t for t in body["tasks"]}
    assert existing["id"] in {t["id"] for t in body["tasks"]}
    login = by_name["Login"]
    untitled = by_name.get(None) or next(t for t in body["tasks"] if not t.get("name"))
    assert login["task"] == "Open /login and sign in"
    assert login["success_criteria"] == "Dashboard is visible"
    assert login["id"] != existing["id"]
    assert untitled["task"] == "Open settings"
    assert untitled["success_criteria"] == "Settings page loads"
    assert untitled["id"] != login["id"]
    assert untitled["id"] != existing["id"]


def test_import_ignores_exported_ids(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    payload = {
        **PACK,
        "tests": [
            {
                "id": "keep-this-id",
                "name": "Copied",
                "task": "Do the thing",
                "success_criteria": "It worked",
                "last_trained_run_id": "run-1",
            }
        ],
    }
    res = client.post(f"/api/websites/{website['id']}/tasks/import", json=payload)
    assert res.status_code == 200
    imported = res.json()["tasks"][0]
    assert imported["id"] != "keep-this-id"
    assert imported["name"] == "Copied"
    assert imported.get("last_trained_run_id") in (None, "")


def test_import_rejects_missing_task_fields(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks/import",
        json={
            "version": 1,
            "kind": "smart-automator.project-tests",
            "tests": [{"name": "Broken", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 422


def test_import_rejects_missing_success_criteria(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks/import",
        json={
            "version": 1,
            "kind": "smart-automator.project-tests",
            "tests": [{"task": "Do it"}],
        },
    )
    assert res.status_code == 422


def test_import_rejects_blank_task_or_criteria(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks/import",
        json={
            "version": 1,
            "kind": "smart-automator.project-tests",
            "tests": [{"task": "   ", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Task is required"


def test_import_rejects_wrong_kind(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks/import",
        json={
            "version": 1,
            "kind": "other.kind",
            "tests": [{"task": "Do it", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 422


def test_import_rejects_empty_pack(client: TestClient) -> None:
    website = client.post("/api/websites", json={"name": "Demo"}).json()
    res = client.post(
        f"/api/websites/{website['id']}/tasks/import",
        json={
            "version": 1,
            "kind": "smart-automator.project-tests",
            "tests": [],
        },
    )
    assert res.status_code == 422


def test_import_unknown_project_is_404(client: TestClient) -> None:
    res = client.post("/api/websites/missing-id/tasks/import", json=PACK)
    assert res.status_code == 404


def test_import_is_scoped_per_user(
    auth_client: TestClient, second_auth_client: TestClient
) -> None:
    created = auth_client.post("/api/websites", json={"name": "Owner"}).json()
    denied = second_auth_client.post(
        f"/api/websites/{created['id']}/tasks/import",
        json=PACK,
    )
    assert denied.status_code == 404
    owner = auth_client.get(f"/api/websites/{created['id']}").json()
    assert owner["tasks"] == []
