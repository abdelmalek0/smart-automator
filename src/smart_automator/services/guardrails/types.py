from enum import Enum
from dataclasses import dataclass
import re


class ThreatType(str, Enum):
    TASK_OVERRIDE = "task_override"
    PROMPT_INJECTION = "prompt_injection"
    SENSITIVE_DATA = "sensitive_data"
    DANGEROUS_ACTION = "dangerous_action"


@dataclass
class SecurityPattern:
    pattern: re.Pattern[str]
    type: ThreatType
    description: str
    replacement: str = ""


@dataclass
class SanitizationResult:
    sanitized: str
    threats: list[ThreatType]
    modified: bool


@dataclass
class ValidationResult:
    is_valid: bool
    threats: list[ThreatType] | None = None
    message: str | None = None
