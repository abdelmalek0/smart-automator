from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..browser.history import DOMHistoryElement
from ..browser.views import TabInfo
from .context import ActionResult


@dataclass
class BrowserStateHistory:
    url: str
    title: str
    tabs: list[TabInfo]
    interacted_elements: list[DOMHistoryElement | None] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "tabs": [{"id": t.id, "url": t.url, "title": t.title} for t in self.tabs],
            "interactedElements": [
                element.to_dict() if element is not None else None
                for element in self.interacted_elements
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserStateHistory:
        tabs = [
            TabInfo(id=t["id"], url=t["url"], title=t["title"])
            for t in data.get("tabs", [])
        ]
        interacted = []
        for item in data.get("interactedElements", data.get("interacted_elements", [])):
            interacted.append(DOMHistoryElement.from_dict(item) if item else None)
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            tabs=tabs,
            interacted_elements=interacted,
        )


@dataclass
class AgentStepRecord:
    model_output: str | None
    result: list[ActionResult]
    state: BrowserStateHistory
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelOutput": self.model_output,
            "result": [
                {
                    "isDone": r.is_done,
                    "success": r.success,
                    "extractedContent": r.extracted_content,
                    "error": r.error,
                    "includeInMemory": r.include_in_memory,
                }
                for r in self.result
            ],
            "state": self.state.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentStepRecord:
        results = []
        for item in data.get("result", []):
            results.append(
                ActionResult(
                    is_done=item.get("isDone", item.get("is_done", False)),
                    success=item.get("success", False),
                    extracted_content=item.get("extractedContent", item.get("extracted_content")),
                    error=item.get("error"),
                    include_in_memory=item.get("includeInMemory", item.get("include_in_memory", False)),
                )
            )
        state_data = data.get("state", {})
        return cls(
            model_output=data.get("modelOutput", data.get("model_output")),
            result=results,
            state=BrowserStateHistory.from_dict(state_data),
            metadata=data.get("metadata"),
        )


@dataclass
class AgentStepHistory:
    history: list[AgentStepRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"history": [record.to_dict() for record in self.history]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentStepHistory:
        records = [
            AgentStepRecord.from_dict(item)
            for item in data.get("history", [])
        ]
        return cls(history=records)
