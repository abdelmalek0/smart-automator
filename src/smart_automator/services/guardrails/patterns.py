import re

from .types import SecurityPattern, ThreatType

SECURITY_PATTERNS: list[SecurityPattern] = [
    SecurityPattern(
        re.compile(r"\b(ignore|forget|disregard)[\s\-_]*(previous|all|above)[\s\-_]*(instructions?|tasks?|commands?)\b", re.I),
        ThreatType.TASK_OVERRIDE,
        "Attempt to override previous instructions",
        "[BLOCKED_OVERRIDE_ATTEMPT]",
    ),
    SecurityPattern(
        re.compile(r"\b(your?|the)[\s\-_]*new[\s\-_]*(task|instruction|goal|objective)[\s\-_]*(is|are|:)", re.I),
        ThreatType.TASK_OVERRIDE,
        "Attempt to inject new task",
        "[BLOCKED_TASK_INJECTION]",
    ),
    SecurityPattern(
        re.compile(r"\b(now|instead|actually)[\s\-_]+(you must|you should|you will)[\s\-_]+", re.I),
        ThreatType.TASK_OVERRIDE,
        "Attempt to redirect agent behavior",
        "[BLOCKED_REDIRECT]",
    ),
    SecurityPattern(
        re.compile(r"\bultimate[-_ ]+task\b", re.I),
        ThreatType.TASK_OVERRIDE,
        "Reference to ultimate task",
        "",
    ),
    SecurityPattern(
        re.compile(r"\bsystem[\s\-_]*(prompt|message|instruction)", re.I),
        ThreatType.PROMPT_INJECTION,
        "Reference to system prompt",
        "[BLOCKED_SYSTEM_REFERENCE]",
    ),
    SecurityPattern(
        re.compile(r"\bnano[-_ ]+untrusted[-_ ]+content\b", re.I),
        ThreatType.PROMPT_INJECTION,
        "Attempt to fake untrusted content tags",
        "",
    ),
    SecurityPattern(
        re.compile(r"\bnano[-_ ]+user[-_ ]+request\b", re.I),
        ThreatType.PROMPT_INJECTION,
        "Attempt to fake user request tags",
        "",
    ),
    SecurityPattern(
        re.compile(r"\buntrusted[-_]+content\b", re.I),
        ThreatType.PROMPT_INJECTION,
        "Reference to untrusted content",
        "",
    ),
    SecurityPattern(
        re.compile(r"\bnano[-_]+attached[-_]+files\b", re.I),
        ThreatType.PROMPT_INJECTION,
        "Reference to attached files",
        "",
    ),
    SecurityPattern(
        re.compile(r"\buser[-_]+request\b", re.I),
        ThreatType.PROMPT_INJECTION,
        "Reference to user request",
        "",
    ),
    SecurityPattern(
        re.compile(r"<\/?[\s]*(?:instruction|command|system|task|override|ignore|plan|execute|request)[\s]*>", re.I),
        ThreatType.PROMPT_INJECTION,
        "Suspicious XML/HTML tags",
        "",
    ),
    SecurityPattern(
        re.compile(r"\]\]>|<!\[CDATA\[", re.I),
        ThreatType.PROMPT_INJECTION,
        "XML injection attempt",
        "",
    ),
    SecurityPattern(
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        ThreatType.SENSITIVE_DATA,
        "Potential SSN detected",
        "[REDACTED_SSN]",
    ),
    SecurityPattern(
        re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b"),
        ThreatType.SENSITIVE_DATA,
        "Potential credit card number",
        "[REDACTED_CC]",
    ),
]

STRICT_PATTERNS: list[SecurityPattern] = [
    SecurityPattern(
        re.compile(r"\b(password|pwd|passwd|api[\s_-]*key|secret|token)\s*[:=]\s*[\"']?[\w-]+[\"']?", re.I),
        ThreatType.SENSITIVE_DATA,
        "Credential detected",
        "[REDACTED_CREDENTIAL]",
    ),
    SecurityPattern(
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        ThreatType.SENSITIVE_DATA,
        "Email address detected",
        "[EMAIL]",
    ),
    SecurityPattern(
        re.compile(r"\b(bypass|circumvent|avoid|skip)[\s\-_]*(security|safety|filter|check)", re.I),
        ThreatType.PROMPT_INJECTION,
        "Security bypass attempt",
        "[BLOCKED_BYPASS]",
    ),
]


def get_patterns(strict: bool = False) -> list[SecurityPattern]:
    return SECURITY_PATTERNS + (STRICT_PATTERNS if strict else [])
