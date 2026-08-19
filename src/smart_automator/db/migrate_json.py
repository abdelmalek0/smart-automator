"""One-shot import of legacy JSON stores into SQLite."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..server import paths
from .engine import get_engine, get_session
from .models import (
    LlmCatalogRow,
    PricingEntryRow,
    RunRow,
    SessionRow,
    UserLlmPrefsRow,
    UserRow,
    WebsiteRow,
    WebsiteTaskRow,
    WorkerTokenRow,
)

log = logging.getLogger(__name__)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Corrupt JSON file: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read file: {path}") from exc
    return data if isinstance(data, dict) else None


def _import_users() -> list[str]:
    data = _load_json_file(paths.USERS_FILE)
    if data is None:
        return []
    users = data.get("users", [])
    if not isinstance(users, list):
        raise RuntimeError(f"Corrupt users file: {paths.USERS_FILE}")
    imported: list[str] = []
    with get_session() as session:
        for item in users:
            if not isinstance(item, dict):
                continue
            user_id = str(item.get("id", ""))
            username = str(item.get("username", ""))
            if not user_id or not username:
                continue
            session.add(
                UserRow(
                    id=user_id,
                    username=username,
                    password_hash=str(item.get("password_hash", "")),
                    created_at=float(item.get("created_at", 0)),
                )
            )
            imported.append(user_id)
    return imported


def _import_sessions() -> None:
    data = _load_json_file(paths.SESSIONS_FILE)
    if data is None:
        return
    sessions = data.get("sessions", [])
    if not isinstance(sessions, list):
        return
    with get_session() as session:
        for item in sessions:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id", ""))
            user_id = str(item.get("user_id", ""))
            if not session_id or not user_id:
                continue
            session.add(
                SessionRow(
                    session_id=session_id,
                    user_id=user_id,
                    created_at=float(item.get("created_at", 0)),
                    expires_at=float(item.get("expires_at", 0)),
                    last_seen_at=float(item.get("last_seen_at", 0)),
                )
            )


def _website_row_from_dict(item: dict[str, Any], user_id: str) -> WebsiteRow:
    website = WebsiteRow(
        id=str(item["id"]),
        user_id=user_id,
        name=str(item.get("name", "")),
        url=str(item.get("url") or ""),
        description=str(item.get("description") or ""),
        context_prompt=str(item.get("context_prompt") or ""),
    )
    for task_data in item.get("tasks", []):
        if not isinstance(task_data, dict):
            continue
        last_trained = task_data.get("last_trained_run_id")
        website.tasks.append(
            WebsiteTaskRow(
                id=str(task_data["id"]),
                website_id=website.id,
                task=str(task_data.get("task", "")),
                success_criteria=str(task_data.get("success_criteria") or ""),
                name=task_data.get("name") or None,
                headless=bool(task_data.get("headless", False)),
                max_steps=int(task_data.get("max_steps", 100)),
                cdp_url=task_data.get("cdp_url") or None,
                fresh_profile=bool(task_data.get("fresh_profile", True)),
                last_trained_run_id=str(last_trained) if last_trained else None,
            )
        )
    return website


def _import_websites(user_ids: list[str]) -> None:
    default_user_id = user_ids[0] if user_ids else ""
    imported_any = False

    with get_session() as session:
        if paths.WEBSITES_DIR.is_dir():
            for path in sorted(paths.WEBSITES_DIR.glob("*.json")):
                user_id = path.stem
                data = _load_json_file(path)
                if data is None:
                    continue
                websites = data.get("websites", []) if isinstance(data, dict) else []
                if not isinstance(websites, list):
                    continue
                for item in websites:
                    if not isinstance(item, dict) or "id" not in item:
                        continue
                    row_user_id = str(item.get("user_id") or user_id)
                    session.add(_website_row_from_dict(item, row_user_id))
                    imported_any = True

        if not imported_any and paths.WEBSITES_FILE.is_file():
            data = _load_json_file(paths.WEBSITES_FILE)
            if data is not None:
                websites = data.get("websites", [])
                if isinstance(websites, list) and websites and default_user_id:
                    for item in websites:
                        if not isinstance(item, dict) or "id" not in item:
                            continue
                        session.add(_website_row_from_dict(item, default_user_id))
                    backup = paths.WEBSITES_FILE.with_suffix(".json.migrated")
                    try:
                        paths.WEBSITES_FILE.replace(backup)
                    except OSError:
                        pass


def _import_runs() -> None:
    runs_dir = paths.RUNS_DIR
    if not runs_dir.is_dir():
        return
    with get_session() as session:
        for user_dir in runs_dir.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            for path in user_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                run_id = str(data.get("run_id", path.stem))
                session.add(
                    RunRow(
                        run_id=run_id,
                        user_id=str(data.get("user_id") or user_id),
                        status=str(data.get("status", "pending")),
                        started_at=float(data.get("started_at", 0)),
                        finished_at=data.get("finished_at"),
                        payload=data,
                    )
                )


def _import_worker_tokens() -> None:
    data = _load_json_file(paths.WORKER_TOKENS_FILE)
    if data is None:
        return
    tokens = data.get("tokens", [])
    if not isinstance(tokens, list):
        return
    with get_session() as session:
        valid_users = set(session.scalars(select(UserRow.id)).all())
        for item in tokens:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token", ""))
            user_id = str(item.get("user_id", ""))
            if not token or not user_id or user_id not in valid_users:
                continue
            session.add(
                WorkerTokenRow(
                    token=token,
                    user_id=user_id,
                    created_at=float(item.get("created_at", 0)),
                )
            )


def _import_user_llm_prefs() -> None:
    llm_dir = paths.LLM_USER_DIR
    if not llm_dir.is_dir():
        return
    with get_session() as session:
        for path in sorted(llm_dir.glob("*.json")):
            user_id = path.stem
            data = _load_json_file(path)
            if data is None:
                continue
            session.add(
                UserLlmPrefsRow(
                    user_id=user_id,
                    provider=str(data.get("provider") or "groq"),
                    models=dict(data.get("models") or {}),
                    api_keys=dict(data.get("api_keys") or {}),
                    openrouter_provider=str(data.get("openrouter_provider") or ""),
                    roles=dict(data.get("roles") or {}),
                )
            )


def _import_llm_catalog() -> None:
    data = _load_json_file(paths.LLM_SETTINGS_FILE)
    if data is None:
        return
    with get_session() as session:
        session.add(LlmCatalogRow(id=1, payload=data))


def _import_pricing() -> None:
    if not paths.PRICING_FILE.is_file():
        return
    try:
        with open(paths.PRICING_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, list):
        return
    with get_session() as session:
        for item in data:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider", "")).strip()
            model = str(item.get("model", "")).strip()
            if not provider or not model:
                continue
            session.add(
                PricingEntryRow(
                    provider=provider,
                    model=model,
                    input_price=float(item.get("input", 0)),
                    output_price=float(item.get("output", 0)),
                    cache_read=float(item.get("cache_read", 0)),
                )
            )


def migrate_schema_if_needed() -> None:
    """Apply lightweight SQLite schema updates for existing databases."""
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    if "user_llm_prefs" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("user_llm_prefs")}
    if "roles" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_llm_prefs ADD COLUMN roles JSON DEFAULT '{}'"))
        log.info("Added roles column to user_llm_prefs")


def migrate_json_if_needed() -> None:
    with get_session() as session:
        existing = session.scalar(select(UserRow.id).limit(1))
        if existing is not None:
            migrate_remaining_json_if_needed()
            return

    log.info("Importing legacy JSON stores into SQLite")
    user_ids = _import_users()
    _import_sessions()
    _import_websites(user_ids)
    _import_runs()
    migrate_remaining_json_if_needed()
    log.info("Legacy JSON import complete")


def migrate_remaining_json_if_needed() -> None:
    with get_session() as session:
        worker_empty = session.scalar(select(WorkerTokenRow.token).limit(1)) is None
        user_llm_empty = session.scalar(select(UserLlmPrefsRow.user_id).limit(1)) is None
        catalog_empty = session.scalar(select(LlmCatalogRow.id).limit(1)) is None
        pricing_empty = session.scalar(select(PricingEntryRow.id).limit(1)) is None
    if worker_empty:
        _import_worker_tokens()
    if user_llm_empty:
        _import_user_llm_prefs()
    if catalog_empty:
        _import_llm_catalog()
    if pricing_empty:
        _import_pricing()


def _safe_unlink(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
        log.info("Removed legacy JSON store file: %s", path)
    except OSError as exc:
        log.warning("Failed to remove legacy JSON store file %s: %s", path, exc)


def _remove_dir_if_empty(path: Path) -> None:
    if not path.is_dir():
        return
    try:
        if any(path.iterdir()):
            return
        path.rmdir()
        log.info("Removed empty legacy data directory: %s", path)
    except OSError as exc:
        log.warning("Failed to remove empty directory %s: %s", path, exc)


def cleanup_migrated_json_files() -> None:
    """Delete legacy JSON store files after corresponding DB tables are populated."""
    with get_session() as session:
        has_users = session.scalar(select(UserRow.id).limit(1)) is not None
        has_runs = session.scalar(select(RunRow.run_id).limit(1)) is not None
        has_websites = session.scalar(select(WebsiteRow.id).limit(1)) is not None
        has_user_llm = session.scalar(select(UserLlmPrefsRow.user_id).limit(1)) is not None

    if has_users:
        for path in (paths.USERS_FILE, paths.SESSIONS_FILE, paths.WORKER_TOKENS_FILE):
            _safe_unlink(path)
        _remove_dir_if_empty(paths.AUTH_DIR)

    if has_runs and paths.RUNS_DIR.is_dir():
        for path in paths.RUNS_DIR.rglob("*.json"):
            _safe_unlink(path)
        for user_dir in sorted(paths.RUNS_DIR.iterdir(), reverse=True):
            if user_dir.is_dir():
                _remove_dir_if_empty(user_dir)
        _remove_dir_if_empty(paths.RUNS_DIR)

    if has_websites:
        if paths.WEBSITES_DIR.is_dir():
            for path in paths.WEBSITES_DIR.glob("*.json"):
                _safe_unlink(path)
            _remove_dir_if_empty(paths.WEBSITES_DIR)
        _safe_unlink(paths.WEBSITES_FILE)
        migrated = paths.WEBSITES_FILE.with_suffix(".json.migrated")
        _safe_unlink(migrated)

    if has_user_llm and paths.LLM_USER_DIR.is_dir():
        for path in paths.LLM_USER_DIR.glob("*.json"):
            _safe_unlink(path)
        _remove_dir_if_empty(paths.LLM_USER_DIR)
