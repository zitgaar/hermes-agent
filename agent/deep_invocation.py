"""Shared helpers for explicit Deep runtime invocations.

A leading ``deep:`` / ``deep：`` is a Deep Runtime MA request. Runtime callers
must either run the real Deep multi-agent producer or fail closed; they must not
silently fall back to the textual ``/deep`` skill scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DeepSource = Literal["prefix", "slash_command"]
DeepMode = Literal["deep"]

_DEEP_PREFIXES = ("deep:", "deep：")
_DEEP_SKILL_SCAFFOLD_PREFIX = '[IMPORTANT: The user has invoked the "deep" skill'


@dataclass(frozen=True)
class DeepInvocation:
    """A parsed explicit Deep runtime invocation for one user turn."""

    source: DeepSource
    mode: DeepMode
    raw_text: str
    user_instruction: str


def detect_deep_invocation(text: str) -> DeepInvocation | None:
    """Return an invocation when *text* starts with explicit ``deep:``.

    The grammar is deliberately narrow: only the first non-whitespace
    characters may be ``deep:`` or ``deep：``. Ordinary prose that merely
    mentions the token must not route into Deep Runtime MA.
    """
    if not isinstance(text, str):
        return None

    stripped = text.lstrip()
    lowered = stripped.lower()
    for marker in _DEEP_PREFIXES:
        if not lowered.startswith(marker):
            continue
        instruction = stripped[len(marker) :].lstrip()
        if not instruction:
            return None
        return DeepInvocation(
            source="prefix",
            mode="deep",
            raw_text=text,
            user_instruction=instruction,
        )
    return None


def is_deep_skill_invocation_scaffold(text: str) -> bool:
    """Return True for Hermes' generated textual ``/deep`` skill scaffold."""
    return isinstance(text, str) and text.startswith(_DEEP_SKILL_SCAFFOLD_PREFIX)


def deep_mechanism_start_payload(source: DeepSource) -> dict[str, str]:
    """Build the canonical lifecycle payload for a Deep runtime start event."""
    return {
        "key": "skill:deep",
        "kind": "multi_agent",
        "label": "deep",
        "name": "deep",
        "phase": "start",
        "scope": "turn",
        "source": source,
    }
