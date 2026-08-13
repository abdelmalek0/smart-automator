from fastapi.testclient import TestClient

PACK = {
    "version": 1,
    "kind": "smart-automator.project",
    "project": {
        "name": "My Shop",
        "description": "Checkout flows",
        "url": "https://shop.example.com",
        "context_prompt": "Use demo account",
    },
    "tests": [
        {
            "name": "Login",
            "task": "Open /login and sign in",
            "success_criteria": "Dashboard is visible",
        }
    ],
}


def test_import_creates_project_with_metadata_and_tests(client: TestClient) -> None:
    res = client.post("/api/websites/import", json=PACK)
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "My Shop"
    assert body["description"] == "Checkout flows"
    assert body["url"] == "https://shop.example.com"
    assert body["context_prompt"] == "Use demo account"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["name"] == "Login"
    assert body["tasks"][0]["task"] == "Open /login and sign in"
    assert body["tasks"][0]["success_criteria"] == "Dashboard is visible"
    assert body["tasks"][0]["id"]


def test_import_allows_empty_tests(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "smart-automator.project",
            "project": {"name": "Empty"},
            "tests": [],
        },
    )
    assert res.status_code == 201
    assert res.json()["tasks"] == []


def test_import_ignores_exported_ids(client: TestClient) -> None:
    payload = {
        **PACK,
        "id": "old-project-id",
        "tests": [
            {
                "id": "old-task-id",
                "name": "Login",
                "task": "Sign in",
                "success_criteria": "Dashboard visible",
                "last_trained_run_id": "run-1",
            }
        ],
    }
    res = client.post("/api/websites/import", json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["id"] != "old-project-id"
    assert body["tasks"][0]["id"] != "old-task-id"
    assert body["tasks"][0].get("last_trained_run_id") in (None, "")


def test_import_rejects_tests_only_pack(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "smart-automator.project-tests",
            "tests": [{"task": "Do it", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 422


def test_import_rejects_wrong_kind(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "other.kind",
            "project": {"name": "Demo"},
            "tests": [],
        },
    )
    assert res.status_code == 422


def test_import_rejects_missing_name(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "smart-automator.project",
            "project": {"name": "   "},
            "tests": [],
        },
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Name is required"


def test_import_rejects_invalid_test_entry(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "smart-automator.project",
            "project": {"name": "Demo"},
            "tests": [{"name": "Broken", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 422


def test_import_rejects_blank_task(client: TestClient) -> None:
    res = client.post(
        "/api/websites/import",
        json={
            "version": 1,
            "kind": "smart-automator.project",
            "project": {"name": "Demo"},
            "tests": [{"task": "   ", "success_criteria": "ok"}],
        },
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Task is required"


def test_imported_project_belongs_to_importer(
    auth_client: TestClient, second_auth_client: TestClient
) -> None:
    res = auth_client.post("/api/websites/import", json=PACK)
    assert res.status_code == 201
    project_id = res.json()["id"]

    owner_list = auth_client.get("/api/websites").json()
    assert any(item["id"] == project_id for item in owner_list)

    other_list = second_auth_client.get("/api/websites").json()
    assert all(item["id"] != project_id for item in other_list)

    denied = second_auth_client.get(f"/api/websites/{project_id}")
    assert denied.status_code == 404
