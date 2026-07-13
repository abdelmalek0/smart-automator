from __future__ import annotations

_JSON_MODE_HINT = "Respond using valid JSON only."


def ensure_json_keyword_in_messages(messages: list[dict]) -> list[dict]:
    """Groq/OpenAI json_object mode requires the word 'json' somewhere in messages."""
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str) and "json" in content.lower():
            return messages

    prepared = [dict(message) for message in messages]
    for index, message in enumerate(prepared):
        if message.get("role") == "system":
            prepared[index] = {
                **message,
                "content": f"{message.get('content', '')}\n\n{_JSON_MODE_HINT}",
            }
            return prepared

    prepared.insert(0, {"role": "system", "content": _JSON_MODE_HINT})
    return prepared
