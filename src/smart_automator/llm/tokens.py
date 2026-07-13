from __future__ import annotations

import json
import re
from typing import Any

# Per-message overhead used by chat APIs (role, separators).
_MESSAGE_OVERHEAD_TOKENS = 4


def count_text_tokens(text: str, *, model: str | None = None) -> int:
    """Lightweight token estimate — no external tokenizer dependency."""
    del model  # reserved for future provider-specific tuning
    if not text:
        return 0

    # Word-ish chunks: closer to real tokenizers than len(text) // 3.
    words = re.findall(r"\S+", text)
    if not words:
        return max(1, len(text) // 4)
    return max(1, sum(max(1, (len(word) + 3) // 4) for word in words))


def count_message_tokens(message: dict[str, Any], *, model: str | None = None) -> int:
    content = message.get("content", "")
    text = content if isinstance(content, str) else json.dumps(content)
    if message.get("tool_calls"):
        text += json.dumps(message["tool_calls"])
    return _MESSAGE_OVERHEAD_TOKENS + count_text_tokens(text, model=model)
