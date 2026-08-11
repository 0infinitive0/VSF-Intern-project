"""High-confidence, zero-token detection for user jailbreak attempts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

JailbreakReason = Literal[
    "instruction_override",
    "prompt_exfiltration",
    "role_spoofing",
    "jailbreak_persona",
]


@dataclass(frozen=True)
class JailbreakDecision:
    blocked: bool
    reason: JailbreakReason | None = None


_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")
_PROMPT_EXTRACTION = re.compile(
    r"\b(?:reveal|show|repeat|print|disclose|tiet lo|hien thi|lap lai)\b.*\b"
    r"(?:system prompt|hidden prompts?|hidden instructions?|developer message|prompt he thong|huong dan an)\b"
)
_ROLE_SPOOFING = re.compile(
    r"(?:<\s*(?:system|developer)\s*>|\b(?:system|developer)\s*(?:message|prompt)\s*:|"
    r"\b(?:developer|unrestricted)\s+mode\b).*(?:ignore|bypass|override|bo qua|vo hieu hoa)"
)
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget|bypass|override|bo qua|vo hieu hoa)\b.*\b"
    r"(?:previous\s+(?:instructions?|rules?)|prior\s+(?:instructions?|rules?)|"
    r"(?:system|developer)\s+(?:instructions?|rules?|prompt)|hidden\s+instructions?|"
    r"huong dan\s+(?:he thong|truoc do)|quy tac\s+he thong)\b"
)
_JAILBREAK_PERSONA = re.compile(
    r"\b(?:act as|you are now|behave as|dong vai|hay la)\b.*\b(?:dan|jailbreak|unrestricted)\b"
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _ZERO_WIDTH.sub("", normalized)
    normalized = normalized.replace("Đ", "D").replace("đ", "d")
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", normalized)
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", normalized).casefold().strip()


def detect_jailbreak(text: str | None) -> JailbreakDecision:
    """Block only explicit attempts to override or extract model instructions."""
    normalized = _normalize(text or "")
    if not normalized:
        return JailbreakDecision(blocked=False)
    if _ROLE_SPOOFING.search(normalized):
        return JailbreakDecision(blocked=True, reason="role_spoofing")
    if _PROMPT_EXTRACTION.search(normalized):
        return JailbreakDecision(blocked=True, reason="prompt_exfiltration")
    if _INSTRUCTION_OVERRIDE.search(normalized):
        return JailbreakDecision(blocked=True, reason="instruction_override")
    if _JAILBREAK_PERSONA.search(normalized):
        return JailbreakDecision(blocked=True, reason="jailbreak_persona")
    return JailbreakDecision(blocked=False)
