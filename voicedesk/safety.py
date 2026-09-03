"""Safety gates: confirmation parsing and risk escalation.

Deliberately free of GUI imports so it can be unit tested in CI without a
display. These two functions decide whether the assistant is allowed to
touch anything, so they are the last place that should be untested.
"""

from __future__ import annotations

import re

import voicedesk.config as cfg
from voicedesk.actions import Action, Risk

AFFIRMATIVE = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "proceed",
    "confirm",
    "confirmed",
    "affirmative",
    "ok",
    "okay",
    "go",
    "do",
    "continue",
}

# Negation wins over affirmation, so "no, go ahead" is treated as a refusal.
# Erring toward refusal is the correct bias for an agent holding the mouse.
NEGATIVE = {
    "no",
    "nope",
    "nah",
    "stop",
    "cancel",
    "dont",
    "don",
    "abort",
    "wait",
    "never",
    "negative",
}

_WORDS = re.compile(r"[a-z]+")

SHELL_WINDOW = re.compile(
    r"(command prompt|powershell|windows terminal|cmd\.exe|terminal|iterm|bash|zsh)",
    re.IGNORECASE,
)


def parse_confirmation(response: str) -> bool:
    """Word-boundary confirmation parsing, with negation taking priority.

    The old check was a substring scan over a phrase set that included
    "do it", so "no, don't do it" *contained* "do it" and was read as
    consent. "ok" also matched inside unrelated words such as "spoke",
    "look", and "broke", meaning ambient speech could approve a
    destructive action.
    """
    words = set(_WORDS.findall(response.lower()))
    if not words:
        return False
    if words & NEGATIVE:
        return False
    return bool(words & AFFIRMATIVE)


def effective_risk(action: Action, active_window: str = "") -> Risk:
    """Escalate an action's risk based on where it will land.

    Typing is normally harmless, but typing into a shell is how a
    misheard word becomes a destroyed working directory. The old
    ``_DANGEROUS_ACTIONS`` set contained only "drag", leaving both ``type``
    and ``open_app`` entirely unguarded.
    """
    if action.action == "type" and SHELL_WINDOW.search(active_window or ""):
        return Risk.DESTRUCTIVE
    if action.action == "open_app":
        name = str(getattr(action, "name", "")).strip().lower()
        if name in cfg.SHELL_APPS:
            return Risk.DESTRUCTIVE
    return action.risk


def needs_confirmation(risk: Risk) -> bool:
    return cfg.CONFIRM_DANGEROUS and risk is Risk.DESTRUCTIVE
