"""JSON-backed persistence for websites and their test tasks."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..server import paths as server_paths
from ..server.paths import WEBSITES_FILE


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


@dataclass
class WebsiteTask:
    id: str
    task: str
    success_criteria: str = ""
    name: str | None = None
    headless: bool = False
    max_steps: int = 100
    cdp_url: str | None = None
    fresh_profile: bool = True
    last_trained_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("name") is None:
            data.pop("name", None)
        if data.get("last_trained_run_id") is None:
            data.pop("last_trained_run_id", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebsiteTask:
        last_trained = data.get("last_trained_run_id")
        return cls(
            id=str(data["id"]),
            task=str(data["task"]),
            success_criteria=str(data.get("success_criteria") or ""),
            name=data.get("name") or None,
            headless=bool(data.get("headless", False)),
            max_steps=int(data.get("max_steps", 100)),
            cdp_url=data.get("cdp_url") or None,
            fresh_profile=bool(data.get("fresh_profile", True)),
            last_trained_run_id=str(last_trained) if last_trained else None,
        )


@dataclass
class Website:
    id: str
    name: str
    url: str = ""
    context_prompt: str = ""
    tasks: list[WebsiteTask] = field(default_factory=list)
    user_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "context_prompt": self.context_prompt,
            "tasks": [t.to_dict() for t in self.tasks],
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, user_id: str = "") -> Website:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            url=str(data.get("url") or ""),
            context_prompt=str(data.get("context_prompt") or ""),
            tasks=[WebsiteTask.from_dict(t) for t in data.get("tasks", [])],
            user_id=str(data.get("user_id") or user_id),
        )


class WebsiteStore:
    def __init__(self, user_id: str, path: Path | None = None) -> None:
        self._user_id = user_id
        self._path = path or (server_paths.WEBSITES_DIR / f"{user_id}.json")
        self._lock = threading.Lock()
        self._maybe_migrate_legacy()

    def _maybe_migrate_legacy(self) -> None:
        if self._path.exists() or not WEBSITES_FILE.exists():
            return
        # Only the first per-user store should claim the legacy file; otherwise every
        # new account would get a copy of the same websites.
        try:
            if any(server_paths.WEBSITES_DIR.glob("*.json")):
                return
        except OSError:
            return
        try:
            with open(WEBSITES_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return
        websites = data.get("websites", []) if isinstance(data, dict) else []
        if not isinstance(websites, list) or not websites:
            return
        migrated = []
        for item in websites:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["user_id"] = self._user_id
            migrated.append(item)
        if not migrated:
            return
        self._save_raw(migrated)
        backup = WEBSITES_FILE.with_suffix(".json.migrated")
        try:
            WEBSITES_FILE.replace(backup)
        except OSError:
            pass

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(data, dict):
            websites = data.get("websites", [])
        elif isinstance(data, list):
            websites = data
        else:
            websites = []
        return websites if isinstance(websites, list) else []

    def _save_raw(self, websites: list[dict[str, Any]]) -> None:
        _atomic_write_json(self._path, {"websites": websites})

    def list_websites(self) -> list[Website]:
        with self._lock:
            return [
                Website.from_dict(w, user_id=self._user_id)
                for w in self._load_raw()
                if not w.get("user_id") or w.get("user_id") == self._user_id
            ]

    def get_website(self, website_id: str) -> Website | None:
        for website in self.list_websites():
            if website.id == website_id:
                return website
        return None

    def create_website(self, name: str, url: str = "", context_prompt: str = "") -> Website:
        website = Website(
            id=str(uuid.uuid4()),
            name=name.strip(),
            url=(url or "").strip(),
            context_prompt=(context_prompt or "").strip(),
            tasks=[],
            user_id=self._user_id,
        )
        with self._lock:
            raw = self._load_raw()
            raw.append(website.to_dict())
            self._save_raw(raw)
        return website

    def update_website(
        self,
        website_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        context_prompt: str | None = None,
    ) -> Website | None:
        with self._lock:
            raw = self._load_raw()
            for item in raw:
                if item.get("id") != website_id:
                    continue
                if item.get("user_id") and item.get("user_id") != self._user_id:
                    continue
                if name is not None:
                    item["name"] = name.strip()
                if url is not None:
                    item["url"] = url.strip()
                if context_prompt is not None:
                    item["context_prompt"] = context_prompt.strip()
                item["user_id"] = self._user_id
                self._save_raw(raw)
                return Website.from_dict(item, user_id=self._user_id)
        return None

    def delete_website(self, website_id: str) -> bool:
        with self._lock:
            raw = self._load_raw()
            next_raw = [
                w
                for w in raw
                if not (w.get("id") == website_id and (not w.get("user_id") or w.get("user_id") == self._user_id))
            ]
            if len(next_raw) == len(raw):
                return False
            self._save_raw(next_raw)
            return True

    def add_task(
        self,
        website_id: str,
        *,
        task: str,
        success_criteria: str,
        name: str | None = None,
        headless: bool = False,
        max_steps: int = 100,
        cdp_url: str | None = None,
        fresh_profile: bool = True,
    ) -> WebsiteTask | None:
        new_task = WebsiteTask(
            id=str(uuid.uuid4()),
            task=task.strip(),
            success_criteria=success_criteria.strip(),
            name=name.strip() if name else None,
            headless=headless,
            max_steps=max_steps,
            cdp_url=cdp_url or None,
            fresh_profile=fresh_profile,
        )
        with self._lock:
            raw = self._load_raw()
            for item in raw:
                if item.get("id") != website_id:
                    continue
                if item.get("user_id") and item.get("user_id") != self._user_id:
                    continue
                tasks = item.setdefault("tasks", [])
                tasks.append(new_task.to_dict())
                item["user_id"] = self._user_id
                self._save_raw(raw)
                return new_task
        return None

    def update_task(
        self,
        website_id: str,
        task_id: str,
        **fields: Any,
    ) -> WebsiteTask | None:
        with self._lock:
            raw = self._load_raw()
            for item in raw:
                if item.get("id") != website_id:
                    continue
                if item.get("user_id") and item.get("user_id") != self._user_id:
                    continue
                for task_data in item.get("tasks", []):
                    if task_data.get("id") != task_id:
                        continue
                    if "task" in fields and fields["task"] is not None:
                        task_data["task"] = str(fields["task"]).strip()
                    if "success_criteria" in fields and fields["success_criteria"] is not None:
                        task_data["success_criteria"] = str(fields["success_criteria"]).strip()
                    if "name" in fields:
                        name_value = fields["name"]
                        task_data["name"] = name_value.strip() if name_value else None
                    if "headless" in fields and fields["headless"] is not None:
                        task_data["headless"] = bool(fields["headless"])
                    if "max_steps" in fields and fields["max_steps"] is not None:
                        task_data["max_steps"] = int(fields["max_steps"])
                    if "cdp_url" in fields:
                        task_data["cdp_url"] = fields["cdp_url"] or None
                    if "fresh_profile" in fields and fields["fresh_profile"] is not None:
                        task_data["fresh_profile"] = bool(fields["fresh_profile"])
                    if "last_trained_run_id" in fields:
                        last_trained = fields["last_trained_run_id"]
                        task_data["last_trained_run_id"] = (
                            str(last_trained).strip() if last_trained else None
                        )
                    self._save_raw(raw)
                    return WebsiteTask.from_dict(task_data)
        return None

    def clear_last_trained_run_id(self, run_id: str) -> None:
        """Clear last_trained_run_id on any task that points to run_id."""
        with self._lock:
            raw = self._load_raw()
            changed = False
            for item in raw:
                if item.get("user_id") and item.get("user_id") != self._user_id:
                    continue
                for task_data in item.get("tasks", []):
                    if task_data.get("last_trained_run_id") == run_id:
                        task_data["last_trained_run_id"] = None
                        changed = True
            if changed:
                self._save_raw(raw)

    def delete_task(self, website_id: str, task_id: str) -> bool:
        with self._lock:
            raw = self._load_raw()
            for item in raw:
                if item.get("id") != website_id:
                    continue
                if item.get("user_id") and item.get("user_id") != self._user_id:
                    continue
                tasks = item.get("tasks", [])
                next_tasks = [t for t in tasks if t.get("id") != task_id]
                if len(next_tasks) == len(tasks):
                    return False
                item["tasks"] = next_tasks
                self._save_raw(raw)
                return True
        return False


def task_to_api_dict(task: WebsiteTask) -> dict[str, Any]:
    from ..server.replay_store import has_replay_script

    data = task.to_dict()
    last_id = task.last_trained_run_id
    if last_id:
        data["last_trained_run_id"] = last_id
    data["has_trained_replay"] = bool(last_id and has_replay_script(last_id))
    return data


def website_to_api_dict(website: Website) -> dict[str, Any]:
    return {
        "id": website.id,
        "name": website.name,
        "url": website.url,
        "context_prompt": website.context_prompt,
        "tasks": [task_to_api_dict(t) for t in website.tasks],
        "user_id": website.user_id,
    }
