from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ...llm.tokens import count_message_tokens
from .utils import (
    filter_external_content,
    split_user_text_and_attachments,
    wrap_attachments,
    wrap_user_request,
)

HISTORY_START_MARKER = "[Your task history memory starts here]"
CURRENT_STATE_MARKER = "[Current state starts here]"
SUMMARY_MARKER = "[Earlier history summarized]"


@dataclass
class MessageMetadata:
    tokens: int
    message_type: str | None = None


@dataclass
class StoredMessage:
    message: dict[str, Any]
    metadata: MessageMetadata


class MessageHistory:
    def __init__(self):
        self.messages: list[StoredMessage] = []
        self.total_tokens = 0

    def add_message(self, message: dict[str, Any], metadata: MessageMetadata, position: int | None = None):
        if position is None:
            self.messages.append(StoredMessage(message=message, metadata=metadata))
        else:
            self.messages.insert(position, StoredMessage(message=message, metadata=metadata))
        self.total_tokens += metadata.tokens

    def remove_message_at(self, index: int) -> StoredMessage | None:
        if index < 0 or index >= len(self.messages):
            return None
        removed = self.messages.pop(index)
        self.total_tokens -= removed.metadata.tokens
        return removed

    def remove_last_state_message(self):
        for i in range(len(self.messages) - 1, -1, -1):
            content = self.messages[i].message.get("content", "")
            if isinstance(content, str) and CURRENT_STATE_MARKER in content:
                self.remove_message_at(i)
                return

    def recalculate_total_tokens(self, token_counter: Callable[[dict[str, Any]], int]):
        total = 0
        for stored in self.messages:
            stored.metadata.tokens = token_counter(stored.message)
            total += stored.metadata.tokens
        self.total_tokens = total


class MessageManagerSettings:
    def __init__(
        self,
        max_input_tokens: int = 128000,
        estimated_characters_per_token: int = 3,
        sensitive_data: dict[str, str] | None = None,
        token_model: str | None = None,
    ):
        self.max_input_tokens = max_input_tokens
        self.estimated_characters_per_token = estimated_characters_per_token
        self.sensitive_data = sensitive_data or {}
        self.token_model = token_model


class MessageManager:
    def __init__(self, settings: MessageManagerSettings | None = None):
        self.settings = settings or MessageManagerSettings()
        self.history = MessageHistory()
        self._tool_id = 1
        self._summary_message_index: int | None = None

    def next_tool_id(self) -> int:
        tool_id = self._tool_id
        self._tool_id += 1
        return tool_id

    def length(self) -> int:
        return len(self.history.messages)

    def init_task_messages(self, system_prompt: str, task: str):
        self.add_message_with_tokens({"role": "system", "content": system_prompt}, "init")

        user_text, attachments_inner = split_user_text_and_attachments(task)
        cleaned_task = filter_external_content(user_text)
        task_content = (
            f'Your ultimate task is: """{cleaned_task}""". '
            "If you achieved your ultimate task, stop everything and use the done action "
            "in the next step to complete the task. If not, continue as usual."
        )
        wrapped = wrap_user_request(task_content, False)
        if attachments_inner:
            wrapped = f"{wrapped}\n\n{wrap_attachments(attachments_inner)}"
        self.add_message_with_tokens({"role": "user", "content": wrapped}, "init")

        self.add_message_with_tokens({"role": "user", "content": "Example output:"}, "init")
        example_output = {
            "current_state": {
                "evaluation_previous_goal": "Success - clicked Apple link from Google results.",
                "memory": "Searched for iPhone retailers. Currently at step 3/15.",
                "next_goal": "Click the iPhone link at index [127].",
            },
            "action": [{"click_element": {"index": 127, "intent": "Open iPhone page"}}],
        }
        self.add_message_with_tokens(
            {
                "role": "assistant",
                "content": json.dumps(example_output),
            },
            "init",
        )
        self.add_message_with_tokens(
            {"role": "user", "content": f"Browser started.\n{HISTORY_START_MARKER}"},
            "init",
        )

    def add_new_task(self, new_task: str):
        user_text, attachments_inner = split_user_text_and_attachments(new_task)
        cleaned_task = filter_external_content(user_text)
        content = (
            f'Your new ultimate task is: """{cleaned_task}""". '
            "This is a follow-up of the previous tasks. Make sure to take all of the "
            "previous context into account and finish your new ultimate task."
        )
        wrapped = wrap_user_request(content, False)
        if attachments_inner:
            wrapped = f"{wrapped}\n\n{wrap_attachments(attachments_inner)}"
        self.add_message_with_tokens({"role": "user", "content": wrapped})

    def add_plan(self, plan: str | None, position: int | None = None):
        if plan:
            cleaned = filter_external_content(plan, False)
            self.add_message_with_tokens(
                {"role": "assistant", "content": f"<plan>{cleaned}</plan>"},
                position=position,
            )

    def add_state_message(self, content: str):
        self.add_message_with_tokens({"role": "user", "content": content})

    def add_model_output(self, model_output: dict):
        self.add_message_with_tokens(
            {
                "role": "assistant",
                "content": json.dumps(model_output),
            }
        )

    def remove_last_state_message(self):
        self.history.remove_last_state_message()

    def add_tool_message(self, content: str, tool_call_id: int | None = None, message_type: str | None = None):
        tool_id = tool_call_id if tool_call_id is not None else self.next_tool_id()
        self.add_message_with_tokens(
            {"role": "tool", "content": content, "tool_call_id": str(tool_id)},
            message_type,
        )

    def get_messages(self) -> list[dict[str, Any]]:
        return [stored.message for stored in self.history.messages]

    def add_message_with_tokens(
        self,
        message: dict[str, Any],
        message_type: str | None = None,
        position: int | None = None,
    ):
        filtered = self._filter_sensitive_data(message)
        tokens = self._count_tokens(filtered)
        metadata = MessageMetadata(tokens=tokens, message_type=message_type)
        self.history.add_message(filtered, metadata, position)
        if position is not None and self._summary_message_index is not None and position <= self._summary_message_index:
            self._summary_message_index += 1

    def _filter_sensitive_data(self, message: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.sensitive_data:
            return message
        result = dict(message)
        content = result.get("content", "")
        if isinstance(content, str):
            for key, value in self.settings.sensitive_data.items():
                if value:
                    content = content.replace(value, f"<secret>{key}</secret>")
            result["content"] = content
        return result

    def _count_tokens(self, message: dict[str, Any]) -> int:
        return max(1, count_message_tokens(message, model=self.settings.token_model))

    def _protected_prefix_end(self) -> int:
        for index, stored in enumerate(self.history.messages):
            content = stored.message.get("content", "")
            if isinstance(content, str) and HISTORY_START_MARKER in content:
                return index + 1
        return min(2, len(self.history.messages))

    def _is_state_message(self, stored: StoredMessage) -> bool:
        content = stored.message.get("content", "")
        return isinstance(content, str) and CURRENT_STATE_MARKER in content

    def _is_summary_message(self, stored: StoredMessage) -> bool:
        content = stored.message.get("content", "")
        return isinstance(content, str) and SUMMARY_MARKER in content

    def _trimmable_indices(self) -> list[int]:
        prefix_end = self._protected_prefix_end()
        indices: list[int] = []
        for index in range(prefix_end, len(self.history.messages)):
            stored = self.history.messages[index]
            if self._is_state_message(stored):
                continue
            if self._is_summary_message(stored):
                continue
            indices.append(index)
        return indices

    def _summarize_removed_messages(self, removed_messages: list[StoredMessage]) -> str:
        lines = [SUMMARY_MARKER, "Dropped older turns to stay within context limits:"]
        for stored in removed_messages[-5:]:
            role = stored.message.get("role", "unknown")
            content = stored.message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content)
            preview = " ".join(content.split())[:180]
            lines.append(f"- {role}: {preview}")
        return "\n".join(lines)

    def _ensure_summary_message(self, removed_messages: list[StoredMessage]) -> None:
        summary = self._summarize_removed_messages(removed_messages)
        if self._summary_message_index is not None:
            index = self._summary_message_index
            if 0 <= index < len(self.history.messages):
                existing = self.history.messages[index]
                self.history.total_tokens -= existing.metadata.tokens
                existing.message = {"role": "user", "content": summary}
                existing.metadata.tokens = self._count_tokens(existing.message)
                self.history.total_tokens += existing.metadata.tokens
                return

        prefix_end = self._protected_prefix_end()
        metadata = MessageMetadata(tokens=self._count_tokens({"role": "user", "content": summary}))
        stored = StoredMessage(message={"role": "user", "content": summary}, metadata=metadata)
        self.history.messages.insert(prefix_end, stored)
        self.history.total_tokens += metadata.tokens
        self._summary_message_index = prefix_end

    def _truncate_last_state_message(self, diff: int) -> bool:
        for index in range(len(self.history.messages) - 1, -1, -1):
            stored = self.history.messages[index]
            if not self._is_state_message(stored):
                continue
            content = stored.message.get("content", "")
            if not isinstance(content, str) or not content:
                return False
            proportion = diff / max(stored.metadata.tokens, 1)
            chars_to_remove = int(len(content) * proportion)
            if proportion > 0.99:
                chars_to_remove = max(chars_to_remove, len(content) // 10, 1)
            new_content = content[:-chars_to_remove] if chars_to_remove else content
            self.history.remove_message_at(index)
            self.add_message_with_tokens({"role": "user", "content": new_content})
            return True
        return False

    def cut_messages(self):
        removed_batch: list[StoredMessage] = []
        guard = 0
        while self.history.total_tokens > self.settings.max_input_tokens and guard < 500:
            guard += 1
            diff = self.history.total_tokens - self.settings.max_input_tokens
            trimmable = self._trimmable_indices()
            if len(trimmable) > 0:
                removed = self.history.remove_message_at(trimmable[0])
                if removed is None:
                    break
                removed_batch.append(removed)
                if self._summary_message_index is not None and trimmable[0] < self._summary_message_index:
                    self._summary_message_index -= 1
                if removed_batch:
                    self._ensure_summary_message(removed_batch)
                continue

            if self._truncate_last_state_message(diff):
                continue

            raise RuntimeError("Max token limit reached - history is too long")
