"""Tests for one-shot JSON-to-SQLite migration."""

from __future__ import annotations

import json

import pytest

from smart_automator.db import init_db, reset_engine
from smart_automator.db.migrate_json import migrate_remaining_json_if_needed
from smart_automator.server.auth.stores import UserStore
from smart_automator.server.config_service import load_pricing
from smart_automator.server.run_store import load_run_record
from smart_automator.server.workers import WorkerTokenStore
from smart_automator.storage.llm_settings import LlmSettingsStore
from smart_automator.storage.user_llm import UserLlmStore
from smart_automator.storage.websites import WebsiteStore


def test_json_migration_imports_core_stores(tmp_path, monkeypatch) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    users_file = auth_dir / "users.json"
    sessions_file = auth_dir / "sessions.json"
    users_file.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "id": "user-1",
                        "username": "alice",
                        "password_hash": "hash",
                        "created_at": 10.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "session_id": "sess-1",
                        "user_id": "user-1",
                        "created_at": 1.0,
                        "expires_at": 9999999999.0,
                        "last_seen_at": 1.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    websites_dir = tmp_path / "websites"
    websites_dir.mkdir(exist_ok=True)
    (websites_dir / "user-1.json").write_text(
        json.dumps(
            {
                "websites": [
                    {
                        "id": "site-1",
                        "name": "Example",
                        "url": "https://example.com",
                        "description": "",
                        "context_prompt": "",
                        "tasks": [
                            {
                                "id": "task-1",
                                "task": "Click",
                                "success_criteria": "Done",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runs_dir = tmp_path / "runs" / "user-1"
    runs_dir.mkdir(parents=True)
    (runs_dir / "run-1.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "user_id": "user-1",
                "status": "pass",
                "started_at": 5.0,
                "finished_at": 6.0,
                "task": "Imported run",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", users_file)
    monkeypatch.setattr("smart_automator.server.paths.SESSIONS_FILE", sessions_file)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", websites_dir)
    monkeypatch.setattr("smart_automator.server.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("smart_automator.server.paths.WORKER_TOKENS_FILE", auth_dir / "worker_tokens.json")
    monkeypatch.setattr("smart_automator.server.paths.LLM_USER_DIR", tmp_path / "llm")
    monkeypatch.setattr("smart_automator.server.paths.LLM_SETTINGS_FILE", tmp_path / "llm_settings.json")
    monkeypatch.setattr("smart_automator.server.paths.PRICING_FILE", tmp_path / "pricing.json")

    (auth_dir / "worker_tokens.json").write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "token": "worker-token-1",
                        "user_id": "user-1",
                        "created_at": 2.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    llm_dir = tmp_path / "llm"
    llm_dir.mkdir()
    (llm_dir / "user-1.json").write_text(
        json.dumps(
            {
                "provider": "groq",
                "models": {"groq": "llama-3.3-70b-versatile"},
                "api_keys": {"groq": "key-1"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "llm_settings.json").write_text(
        json.dumps(
            {
                "providers": {
                    "groq": {
                        "base_url": "https://api.groq.com/openai/v1",
                        "models": ["llama-3.3-70b-versatile"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pricing.json").write_text(
        json.dumps(
            [
                {
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                    "input": 0.5,
                    "output": 0.8,
                    "cache_read": 0.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    reset_engine(f"sqlite:///{tmp_path / 'import.db'}")
    init_db()

    assert UserStore().get_by_id("user-1") is not None
    websites = WebsiteStore("user-1").list_websites()
    assert len(websites) == 1
    assert websites[0].id == "site-1"
    assert websites[0].tasks[0].id == "task-1"

    record = load_run_record("user-1", "run-1")
    assert record is not None
    assert record["task"] == "Imported run"
    assert record["status"] == "pass"

    token = WorkerTokenStore().get_by_token("worker-token-1")
    assert token is not None
    assert token.user_id == "user-1"

    prefs = UserLlmStore("user-1").load()
    assert prefs.provider == "groq"
    assert prefs.api_key_for("groq") == "key-1"

    catalog = LlmSettingsStore().load()
    assert "llama-3.3-70b-versatile" in catalog.get_provider("groq").models

    pricing = load_pricing()
    assert any(row.get("model") == "llama-3.3-70b-versatile" for row in pricing)

    assert not users_file.exists()
    assert not sessions_file.exists()
    assert not (auth_dir / "worker_tokens.json").exists()
    assert not list(websites_dir.glob("*.json"))
    assert not list(llm_dir.glob("*.json"))
    assert not (runs_dir / "run-1.json").exists()
    assert (tmp_path / "llm_settings.json").exists()
    assert (tmp_path / "pricing.json").exists()


def test_cleanup_removes_legacy_json_and_preserves_histories(tmp_path, monkeypatch) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    users_file = auth_dir / "users.json"
    users_file.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "id": "user-1",
                        "username": "alice",
                        "password_hash": "hash",
                        "created_at": 10.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    histories_dir = tmp_path / "histories"
    histories_dir.mkdir()
    history_file = histories_dir / "run-history.json"
    history_file.write_text('{"history": []}', encoding="utf-8")

    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", users_file)
    monkeypatch.setattr("smart_automator.server.paths.SESSIONS_FILE", auth_dir / "sessions.json")
    monkeypatch.setattr("smart_automator.server.paths.WORKER_TOKENS_FILE", auth_dir / "worker_tokens.json")
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", tmp_path / "websites")
    monkeypatch.setattr("smart_automator.server.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("smart_automator.server.paths.LLM_USER_DIR", tmp_path / "llm")
    monkeypatch.setattr("smart_automator.server.paths.HISTORY_DIR", histories_dir)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_FILE", tmp_path / "websites.json")

    reset_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
    init_db()

    assert not users_file.exists()
    assert history_file.exists()
    assert history_file.read_text(encoding="utf-8") == '{"history": []}'


def test_cleanup_skips_when_db_tables_empty(tmp_path, monkeypatch) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    users_file = auth_dir / "users.json"
    users_file.write_text(
        json.dumps({"users": [{"id": "u1", "username": "alice", "password_hash": "x", "created_at": 1}]}),
        encoding="utf-8",
    )
    websites_dir = tmp_path / "websites"
    websites_dir.mkdir(exist_ok=True)
    website_file = websites_dir / "user-1.json"
    website_file.write_text('{"websites": []}', encoding="utf-8")

    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", users_file)
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_DIR", websites_dir)

    reset_engine(f"sqlite:///{tmp_path / 'no-cleanup.db'}")
    from smart_automator.db.engine import get_engine
    from smart_automator.db.migrate_json import cleanup_migrated_json_files
    from smart_automator.db.models import Base

    Base.metadata.create_all(get_engine())
    cleanup_migrated_json_files()

    assert users_file.exists()
    assert website_file.exists()


def test_phase2_migration_runs_when_users_already_exist(tmp_path, monkeypatch) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", auth_dir / "users.json")
    monkeypatch.setattr("smart_automator.server.paths.WORKER_TOKENS_FILE", auth_dir / "worker_tokens.json")
    monkeypatch.setattr("smart_automator.server.paths.LLM_USER_DIR", tmp_path / "llm")
    monkeypatch.setattr("smart_automator.server.paths.LLM_SETTINGS_FILE", tmp_path / "llm_settings.json")
    monkeypatch.setattr("smart_automator.server.paths.PRICING_FILE", tmp_path / "pricing.json")

    db_path = tmp_path / "phase2.db"
    reset_engine(f"sqlite:///{db_path}")
    from smart_automator.db.engine import get_engine
    from smart_automator.db.models import Base

    Base.metadata.create_all(get_engine())
    user = UserStore().create_user("alice", "password123")

    (auth_dir / "worker_tokens.json").write_text(
        json.dumps({"tokens": [{"token": "tok-1", "user_id": user.id, "created_at": 1.0}]}),
        encoding="utf-8",
    )
    llm_dir = tmp_path / "llm"
    llm_dir.mkdir()
    (llm_dir / f"{user.id}.json").write_text(
        json.dumps({"provider": "groq", "models": {"groq": "m"}, "api_keys": {}}),
        encoding="utf-8",
    )
    migrate_remaining_json_if_needed()

    assert WorkerTokenStore().get_by_token("tok-1") is not None
    assert UserLlmStore(user.id).load().selected_model("groq") == "m"


def test_json_migration_skips_when_db_already_has_users(tmp_path, monkeypatch) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(exist_ok=True)
    users_file = auth_dir / "users.json"
    monkeypatch.setattr("smart_automator.server.paths.AUTH_DIR", auth_dir)
    monkeypatch.setattr("smart_automator.server.paths.USERS_FILE", users_file)

    db_path = tmp_path / "skip.db"
    reset_engine(f"sqlite:///{db_path}")
    from smart_automator.db.engine import get_engine
    from smart_automator.db.migrate_json import migrate_json_if_needed
    from smart_automator.db.models import Base

    Base.metadata.create_all(get_engine())
    UserStore().create_user("existing", "password123")

    users_file.write_text(
        json.dumps({"users": [{"id": "other", "username": "bob", "password_hash": "x", "created_at": 1}]}),
        encoding="utf-8",
    )
    migrate_json_if_needed()

    assert UserStore().get_by_id("other") is None
    assert UserStore().get_by_username("existing") is not None


def test_cleanup_removes_stale_root_websites_json(tmp_path, monkeypatch) -> None:
    """Stale root websites.json is removed when DB already has websites (never imported)."""
    websites_file = tmp_path / "websites.json"
    monkeypatch.setattr("smart_automator.server.paths.WEBSITES_FILE", websites_file)

    reset_engine(f"sqlite:///{tmp_path / 'stale-websites.db'}")
    from smart_automator.db.engine import get_engine
    from smart_automator.db.migrate_json import cleanup_migrated_json_files
    from smart_automator.db.models import Base

    Base.metadata.create_all(get_engine())
    user = UserStore().create_user("alice", "password123")
    WebsiteStore(user.id).create_website("Example", url="https://example.com")

    websites_file.write_text(
        json.dumps({"websites": [{"id": "stale", "name": "Stale", "url": "", "tasks": []}]}),
        encoding="utf-8",
    )
    cleanup_migrated_json_files()

    assert not websites_file.exists()
    assert not websites_file.with_suffix(".json.migrated").exists()
