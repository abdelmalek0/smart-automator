import re
import unicodedata

from .patterns import get_patterns
from .types import SanitizationResult, ThreatType, ValidationResult


def clean_empty_tags(content: str) -> str:
    result = re.sub(r"<(\w+)[^>]*>\s*</\1>", "", content)
    result = re.sub(r"<\s*/?\s*>", "", result)
    return result


def sanitize_content(content: str | None, strict: bool = False) -> SanitizationResult:
    if not content or not content.strip():
        return SanitizationResult(sanitized="", threats=[], modified=False)

    sanitized = unicodedata.normalize("NFKC", content)
    sanitized = re.sub(r"[\u200B-\u200D\uFEFF]", "", sanitized)
    detected: set[ThreatType] = set()
    modified = False

    for security_pattern in get_patterns(strict):
        if security_pattern.pattern.search(sanitized):
            detected.add(security_pattern.type)
            original_len = len(sanitized)
            sanitized = security_pattern.pattern.sub(security_pattern.replacement, sanitized)
            if len(sanitized) != original_len:
                modified = True

    if modified:
        sanitized = re.sub(r"[^\S\r\n]+", " ", sanitized)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
        sanitized = clean_empty_tags(sanitized)

    return SanitizationResult(sanitized=sanitized, threats=list(detected), modified=modified)


def detect_threats(content: str, strict: bool = False) -> list[ThreatType]:
    if not content or not content.strip():
        return []
    detected: set[ThreatType] = set()
    for security_pattern in get_patterns(strict):
        if security_pattern.pattern.search(content):
            detected.add(security_pattern.type)
    return list(detected)


class SecurityGuardrails:
    def __init__(self, strict_mode: bool = False, enabled: bool = True):
        self.strict_mode = strict_mode
        self.enabled = enabled

    def sanitize(self, content: str | None, strict: bool | None = None) -> SanitizationResult:
        if not self.enabled:
            return SanitizationResult(sanitized=content or "", threats=[], modified=False)
        return sanitize_content(content, strict if strict is not None else self.strict_mode)

    def detect_threats(self, content: str, strict: bool | None = None) -> list[ThreatType]:
        if not self.enabled:
            return []
        return detect_threats(content, strict if strict is not None else self.strict_mode)

    def validate(self, content: str, strict: bool | None = None) -> ValidationResult:
        if not self.enabled:
            return ValidationResult(is_valid=True)
        effective_strict = strict if strict is not None else self.strict_mode
        threats = self.detect_threats(content, effective_strict)
        if not threats:
            return ValidationResult(is_valid=True)
        if effective_strict:
            return ValidationResult(
                is_valid=False,
                threats=threats,
                message=f"Content contains {len(threats)} security threat(s)",
            )
        critical = [t for t in threats if t in (ThreatType.TASK_OVERRIDE, ThreatType.DANGEROUS_ACTION)]
        return ValidationResult(
            is_valid=len(critical) == 0,
            threats=threats,
            message=(
                f"Content contains {len(critical)} critical threat(s)"
                if critical
                else f"Content contains {len(threats)} non-critical threat(s)"
            ),
        )


guardrails = SecurityGuardrails()
