DANGEROUS_PREFIXES = [
    "https://chromewebstore.google.com",
    "chrome-extension://",
    "chrome://",
    "javascript:",
    "data:",
    "file:",
    "vbscript:",
    "ws:",
    "wss:",
]


def is_url_allowed(url: str, allow_list: list[str], deny_list: list[str]) -> bool:
    trimmed = url.strip()
    if not trimmed:
        return False

    lower = trimmed.lower()
    if any(lower.startswith(prefix) for prefix in DANGEROUS_PREFIXES):
        return False

    if not allow_list and not deny_list:
        return True

    if trimmed == "about:blank":
        return True

    try:
        from urllib.parse import urlparse

        parsed = urlparse(trimmed)
        url_without_protocol = lower.replace("https://", "").replace("http://", "")

        for denied in deny_list:
            if url_without_protocol == denied.lower():
                return False

        for allowed in allow_list:
            if url_without_protocol == allowed.lower():
                return True

        domain = (parsed.hostname or "").lower()
        port_index = domain.find(":")
        if port_index > -1:
            domain = domain[:port_index]

        for denied in deny_list:
            denied_lower = denied.lower()
            if domain == denied_lower or domain.endswith(f".{denied_lower}"):
                return False

        for allowed in allow_list:
            allowed_lower = allowed.lower()
            if domain == allowed_lower or domain.endswith(f".{allowed_lower}"):
                return True

        return len(allow_list) == 0
    except Exception:
        return False


def cap_text_length(text: str, max_length: int) -> str:
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text
