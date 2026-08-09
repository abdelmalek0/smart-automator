from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from ..db.engine import get_session
from ..db.models import WebsiteRow, WebsiteTaskRow


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
    description: str = ""
    context_prompt: str = ""
    tasks: list[WebsiteTask] = field(default_factory=list)
    user_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "description": self.description,
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
            description=str(data.get("description") or ""),
            context_prompt=str(data.get("context_prompt") or ""),
            tasks=[WebsiteTask.from_dict(t) for t in data.get("tasks", [])],
            user_id=str(data.get("user_id") or user_id),
        )


def _task_from_row(row: WebsiteTaskRow) -> WebsiteTask:
    return WebsiteTask(
        id=row.id,
        task=row.task,
        success_criteria=row.success_criteria,
        name=row.name,
        headless=row.headless,
        max_steps=row.max_steps,
        cdp_url=row.cdp_url,
        fresh_profile=row.fresh_profile,
        last_trained_run_id=row.last_trained_run_id,
    )


def _website_from_row(row: WebsiteRow) -> Website:
    return Website(
        id=row.id,
        name=row.name,
        url=row.url,
        description=row.description,
        context_prompt=row.context_prompt,
        tasks=[_task_from_row(task) for task in row.tasks],
        user_id=row.user_id,
    )


class WebsiteStore:
    def __init__(self, user_id: str, path: Path | None = None) -> None:
        # path is ignored; kept for backward compatibility with tests.
        self._user_id = user_id
        self._lock = threading.Lock()

    def list_websites(self) -> list[Website]:
        with self._lock:
            with get_session() as session:
                rows = session.scalars(
                    select(WebsiteRow)
                    .where(WebsiteRow.user_id == self._user_id)
                    .options(selectinload(WebsiteRow.tasks))
                    .order_by(WebsiteRow.name)
                ).all()
                return [_website_from_row(row) for row in rows]

    def get_website(self, website_id: str) -> Website | None:
        for website in self.list_websites():
            if website.id == website_id:
                return website
        return None

    def create_website(
        self,
        name: str,
        url: str = "",
        context_prompt: str = "",
        description: str = "",
    ) -> Website:
        website = Website(
            id=str(uuid.uuid4()),
            name=name.strip(),
            url=(url or "").strip(),
            description=(description or "").strip(),
            context_prompt=(context_prompt or "").strip(),
            tasks=[],
            user_id=self._user_id,
        )
        with self._lock:
            with get_session() as session:
                session.add(
                    WebsiteRow(
                        id=website.id,
                        user_id=self._user_id,
                        name=website.name,
                        url=website.url,
                        description=website.description,
                        context_prompt=website.context_prompt,
                    )
                )
        return website

    def update_website(
        self,
        website_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        description: str | None = None,
        context_prompt: str | None = None,
    ) -> Website | None:
        with self._lock:
            with get_session() as session:
                row = session.scalar(
                    select(WebsiteRow)
                    .where(WebsiteRow.id == website_id, WebsiteRow.user_id == self._user_id)
                    .options(selectinload(WebsiteRow.tasks))
                )
                if row is None:
                    return None
                if name is not None:
                    row.name = name.strip()
                if url is not None:
                    row.url = url.strip()
                if description is not None:
                    row.description = description.strip()
                if context_prompt is not None:
                    row.context_prompt = context_prompt.strip()
                return _website_from_row(row)

    def delete_website(self, website_id: str) -> bool:
        with self._lock:
            with get_session() as session:
                row = session.scalar(
                    select(WebsiteRow).where(
                        WebsiteRow.id == website_id,
                        WebsiteRow.user_id == self._user_id,
                    )
                )
                if row is None:
                    return False
                session.delete(row)
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
            with get_session() as session:
                row = session.scalar(
                    select(WebsiteRow).where(
                        WebsiteRow.id == website_id,
                        WebsiteRow.user_id == self._user_id,
                    )
                )
                if row is None:
                    return None
                session.add(
                    WebsiteTaskRow(
                        id=new_task.id,
                        website_id=website_id,
                        task=new_task.task,
                        success_criteria=new_task.success_criteria,
                        name=new_task.name,
                        headless=new_task.headless,
                        max_steps=new_task.max_steps,
                        cdp_url=new_task.cdp_url,
                        fresh_profile=new_task.fresh_profile,
                    )
                )
                return new_task

    def update_task(
        self,
        website_id: str,
        task_id: str,
        **fields: Any,
    ) -> WebsiteTask | None:
        with self._lock:
            with get_session() as session:
                task_row = session.scalar(
                    select(WebsiteTaskRow)
                    .join(WebsiteRow)
                    .where(
                        WebsiteTaskRow.id == task_id,
                        WebsiteTaskRow.website_id == website_id,
                        WebsiteRow.user_id == self._user_id,
                    )
                )
                if task_row is None:
                    return None
                if "task" in fields and fields["task"] is not None:
                    task_row.task = str(fields["task"]).strip()
                if "success_criteria" in fields and fields["success_criteria"] is not None:
                    task_row.success_criteria = str(fields["success_criteria"]).strip()
                if "name" in fields:
                    name_value = fields["name"]
                    task_row.name = name_value.strip() if name_value else None
                if "headless" in fields and fields["headless"] is not None:
                    task_row.headless = bool(fields["headless"])
                if "max_steps" in fields and fields["max_steps"] is not None:
                    task_row.max_steps = int(fields["max_steps"])
                if "cdp_url" in fields:
                    task_row.cdp_url = fields["cdp_url"] or None
                if "fresh_profile" in fields and fields["fresh_profile"] is not None:
                    task_row.fresh_profile = bool(fields["fresh_profile"])
                if "last_trained_run_id" in fields:
                    last_trained = fields["last_trained_run_id"]
                    task_row.last_trained_run_id = (
                        str(last_trained).strip() if last_trained else None
                    )
                return _task_from_row(task_row)

    def clear_last_trained_run_id(self, run_id: str) -> None:
        with self._lock:
            with get_session() as session:
                rows = session.scalars(
                    select(WebsiteTaskRow)
                    .join(WebsiteRow)
                    .where(
                        WebsiteRow.user_id == self._user_id,
                        WebsiteTaskRow.last_trained_run_id == run_id,
                    )
                ).all()
                for row in rows:
                    row.last_trained_run_id = None

    def delete_task(self, website_id: str, task_id: str) -> bool:
        with self._lock:
            with get_session() as session:
                task_row = session.scalar(
                    select(WebsiteTaskRow)
                    .join(WebsiteRow)
                    .where(
                        WebsiteTaskRow.id == task_id,
                        WebsiteTaskRow.website_id == website_id,
                        WebsiteRow.user_id == self._user_id,
                    )
                )
                if task_row is None:
                    return False
                session.delete(task_row)
                return True


def task_to_api_dict(task: WebsiteTask, *, user_id: str) -> dict[str, Any]:
    from ..server.replay_store import has_replay_script
    from ..server.run_store import load_run_record

    data = task.to_dict()
    last_id = task.last_trained_run_id
    has_trained = False
    if last_id:
        data["last_trained_run_id"] = last_id
        if has_replay_script(last_id):
            record = load_run_record(user_id, last_id)
            has_trained = bool(
                record
                and record.get("status") == "pass"
                and not record.get("use_replay_script", False)
            )
    data["has_trained_replay"] = has_trained
    return data


def website_to_api_dict(website: Website) -> dict[str, Any]:
    return {
        "id": website.id,
        "name": website.name,
        "url": website.url,
        "description": website.description,
        "context_prompt": website.context_prompt,
        "tasks": [task_to_api_dict(t, user_id=website.user_id) for t in website.tasks],
        "user_id": website.user_id,
    }
