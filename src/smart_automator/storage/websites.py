"""JSON-backed persistence for websites and their test tasks."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..server.paths import WEBSITES_FILE


@dataclass
class WebsiteTask:
    id: str
    task: str
    headless: bool = False
    max_steps: int = 100
    cdp_url: str | None = None
    fresh_profile: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebsiteTask:
        return cls(
            id=str(data["id"]),
            task=str(data["task"]),
            headless=bool(data.get("headless", False)),
            max_steps=int(data.get("max_steps", 100)),
            cdp_url=data.get("cdp_url") or None,
            fresh_profile=bool(data.get("fresh_profile", False)),
        )


@dataclass
class Website:
    id: str
    name: str
    url: str = ""
    context_prompt: str = ""
    tasks: list[WebsiteTask] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "context_prompt": self.context_prompt,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Website:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            url=str(data.get("url") or ""),
            context_prompt=str(data.get("context_prompt") or ""),
            tasks=[WebsiteTask.from_dict(t) for t in data.get("tasks", [])],
        )


class WebsiteStore:
    def __init__(self, path: Path = WEBSITES_FILE) -> None:
        self._path = path
        self._lock = threading.Lock()

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"websites": websites}, f, indent=2)
            f.write("\n")

    def list_websites(self) -> list[Website]:
        with self._lock:
            return [Website.from_dict(w) for w in self._load_raw()]

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
                if name is not None:
                    item["name"] = name.strip()
                if url is not None:
                    item["url"] = url.strip()
                if context_prompt is not None:
                    item["context_prompt"] = context_prompt.strip()
                self._save_raw(raw)
                return Website.from_dict(item)
        return None

    def delete_website(self, website_id: str) -> bool:
        with self._lock:
            raw = self._load_raw()
            next_raw = [w for w in raw if w.get("id") != website_id]
            if len(next_raw) == len(raw):
                return False
            self._save_raw(next_raw)
            return True

    def add_task(
        self,
        website_id: str,
        *,
        task: str,
        headless: bool = False,
        max_steps: int = 100,
        cdp_url: str | None = None,
        fresh_profile: bool = False,
    ) -> WebsiteTask | None:
        new_task = WebsiteTask(
            id=str(uuid.uuid4()),
            task=task.strip(),
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
                tasks = item.setdefault("tasks", [])
                tasks.append(new_task.to_dict())
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
                for task_data in item.get("tasks", []):
                    if task_data.get("id") != task_id:
                        continue
                    if "task" in fields and fields["task"] is not None:
                        task_data["task"] = str(fields["task"]).strip()
                    if "headless" in fields and fields["headless"] is not None:
                        task_data["headless"] = bool(fields["headless"])
                    if "max_steps" in fields and fields["max_steps"] is not None:
                        task_data["max_steps"] = int(fields["max_steps"])
                    if "cdp_url" in fields:
                        task_data["cdp_url"] = fields["cdp_url"] or None
                    if "fresh_profile" in fields and fields["fresh_profile"] is not None:
                        task_data["fresh_profile"] = bool(fields["fresh_profile"])
                    self._save_raw(raw)
                    return WebsiteTask.from_dict(task_data)
        return None

    def delete_task(self, website_id: str, task_id: str) -> bool:
        with self._lock:
            raw = self._load_raw()
            for item in raw:
                if item.get("id") != website_id:
                    continue
                tasks = item.get("tasks", [])
                next_tasks = [t for t in tasks if t.get("id") != task_id]
                if len(next_tasks) == len(tasks):
                    return False
                item["tasks"] = next_tasks
                self._save_raw(raw)
                return True
        return False
