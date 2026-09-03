"""Typed, validated action schema for VoiceDesk.

The model returns a JSON array of actions. None of it is trusted. Every plan
is normalized and then strictly validated *before* the executor performs a
single side effect, so a malformed or hostile plan fails closed instead of
half-executing and leaving the desktop in an unknown state.

The previous executor validated while running: it raised on an unknown
action partway through a loop, after the earlier actions had already fired,
with no way to roll back.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Risk(str, Enum):
    """How much damage an action can do if the model got it wrong."""

    READ = "read"  # observable only, no side effect
    WRITE = "write"  # changes UI state, easily reversible
    LAUNCH = "launch"  # starts a process
    DESTRUCTIVE = "destructive"  # may close, delete, or lose work


RISK_ORDER = [Risk.READ, Risk.WRITE, Risk.LAUNCH, Risk.DESTRUCTIVE]

MODIFIER_KEYS = {
    "ctrl",
    "control",
    "alt",
    "option",
    "shift",
    "cmd",
    "command",
    "win",
    "super",
    "meta",
}

KEY_ALIASES = {
    "control": "ctrl",
    "command": "cmd",
    "option": "alt",
    "super": "win",
    "meta": "win",
    "return": "enter",
    "esc": "escape",
    "del": "delete",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "spacebar": "space",
}

DESTRUCTIVE_KEYS = {"delete", "backspace", "f4"}

DESTRUCTIVE_COMBOS: tuple[frozenset[str], ...] = (
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "w"}),
    frozenset({"ctrl", "q"}),
    frozenset({"cmd", "w"}),
    frozenset({"cmd", "q"}),
    frozenset({"shift", "delete"}),
    frozenset({"ctrl", "shift", "delete"}),
)

MAX_WAIT_SECONDS = 30.0
MAX_TYPE_CHARS = 2000


class PlanError(ValueError):
    """Raised when the model's plan cannot be trusted."""


def canonical_key(key: Any) -> str:
    lowered = str(key).strip().lower()
    return KEY_ALIASES.get(lowered, lowered)


# -- action types --------------------------------------------------------


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @property
    def risk(self) -> Risk:
        return Risk.WRITE

    def describe(self) -> str:
        return str(getattr(self, "action", "action"))


class _Point(_Action):
    """Coordinates are mandatory.

    The old ``_numbers`` helper happily returned ``None``, and
    ``pyautogui.click(x=None, y=None)`` clicks wherever the cursor happens
    to be sitting: a random click into whatever currently has focus.
    """

    x: int = Field(ge=-20000, le=20000)
    y: int = Field(ge=-20000, le=20000)


class Click(_Point):
    action: Literal["click"]

    def describe(self) -> str:
        return f"click at ({self.x}, {self.y})"


class DoubleClick(_Point):
    action: Literal["double_click"]

    def describe(self) -> str:
        return f"double-click at ({self.x}, {self.y})"


class RightClick(_Point):
    action: Literal["right_click"]

    def describe(self) -> str:
        return f"right-click at ({self.x}, {self.y})"


class Move(_Point):
    action: Literal["move"]
    duration: float = Field(default=0.0, ge=0.0, le=5.0)

    @property
    def risk(self) -> Risk:
        return Risk.READ

    def describe(self) -> str:
        return f"move to ({self.x}, {self.y})"


class Scroll(_Point):
    action: Literal["scroll"]
    clicks: int = Field(ge=-50, le=50)

    def describe(self) -> str:
        direction = "up" if self.clicks >= 0 else "down"
        return f"scroll {direction} {abs(self.clicks)} at ({self.x}, {self.y})"


class Drag(_Point):
    action: Literal["drag"]
    duration: float = Field(default=0.2, ge=0.0, le=5.0)

    @property
    def risk(self) -> Risk:
        return Risk.DESTRUCTIVE

    def describe(self) -> str:
        return f"drag to ({self.x}, {self.y})"


class Type(_Action):
    action: Literal["type"]
    text: str = Field(min_length=1, max_length=MAX_TYPE_CHARS)

    def describe(self) -> str:
        preview = self.text[:40]
        suffix = "..." if len(self.text) > 40 else ""
        return f"type {preview!r}{suffix}"


class Press(_Action):
    """Taps keys one at a time. Chords belong in :class:`Hotkey`."""

    action: Literal["press"]
    keys: list[str] = Field(min_length=1, max_length=10)

    @property
    def risk(self) -> Risk:
        if set(self.keys) & DESTRUCTIVE_KEYS:
            return Risk.DESTRUCTIVE
        return Risk.WRITE

    def describe(self) -> str:
        return f"press {', '.join(self.keys)}"


class Hotkey(_Action):
    action: Literal["hotkey"]
    keys: list[str] = Field(min_length=1, max_length=6)

    @property
    def risk(self) -> Risk:
        pressed = set(self.keys)
        if pressed & DESTRUCTIVE_KEYS:
            return Risk.DESTRUCTIVE
        if any(combo <= pressed for combo in DESTRUCTIVE_COMBOS):
            return Risk.DESTRUCTIVE
        return Risk.WRITE

    def describe(self) -> str:
        return f"press {' + '.join(self.keys)}"


class OpenApp(_Action):
    action: Literal["open_app"]
    name: str = Field(min_length=1, max_length=64)

    @property
    def risk(self) -> Risk:
        return Risk.LAUNCH

    def describe(self) -> str:
        return f"open {self.name}"


class Speak(_Action):
    action: Literal["speak"]
    text: str = Field(min_length=1, max_length=1000)

    @property
    def risk(self) -> Risk:
        return Risk.READ

    def describe(self) -> str:
        return f"say {self.text[:60]!r}"


class Wait(_Action):
    action: Literal["wait"]
    seconds: float = Field(gt=0.0, le=MAX_WAIT_SECONDS)

    @property
    def risk(self) -> Risk:
        return Risk.READ

    def describe(self) -> str:
        return f"wait {self.seconds:g}s"


Action = Annotated[
    Union[
        Click,
        DoubleClick,
        RightClick,
        Move,
        Scroll,
        Drag,
        Type,
        Press,
        Hotkey,
        OpenApp,
        Speak,
        Wait,
    ],
    Field(discriminator="action"),
]

_PLAN_ADAPTER: TypeAdapter[list[Action]] = TypeAdapter(list[Action])

POINT_ACTIONS = {"click", "double_click", "right_click", "move", "scroll", "drag"}


# -- normalization and validation ---------------------------------------


def normalize_plan(raw: Any) -> list[dict]:
    """Repair the shapes models actually emit, before strict validation.

    The important one: models routinely return
    ``{"action": "press", "keys": ["ctrl", "c"]}`` when they mean a chord.
    The old ``_press_many`` pressed those sequentially, so "copy this"
    typed the letter c instead of copying.
    """
    if isinstance(raw, dict):
        raw = raw.get("actions", [raw])
    if not isinstance(raw, list):
        raise PlanError("plan must be a JSON array of actions")

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip().lower()
        if not action:
            continue

        entry = {k: v for k, v in item.items() if not str(k).startswith("_")}
        entry["action"] = action

        if action in {"press", "hotkey"}:
            keys = entry.get("keys")
            if keys is None:
                text = entry.get("text")
                keys = [text] if text else []
            if isinstance(keys, str):
                keys = [keys]
            keys = [canonical_key(k) for k in keys if str(k).strip()]
            entry.pop("text", None)
            entry["keys"] = keys
            if action == "press" and len(keys) > 1 and set(keys) & MODIFIER_KEYS:
                entry["action"] = "hotkey"

        if action == "scroll" and entry.get("clicks") is None:
            entry["clicks"] = 0

        normalized.append(entry)

    return normalized


def parse_plan(raw: Any) -> list[Action]:
    """Normalize then strictly validate. Raises :class:`PlanError`."""
    try:
        return _PLAN_ADAPTER.validate_python(normalize_plan(raw))
    except PlanError:
        raise
    except Exception as exc:  # pydantic ValidationError
        raise PlanError(str(exc)) from exc


def highest_risk(actions: list[Action]) -> Risk:
    if not actions:
        return Risk.READ
    return max((a.risk for a in actions), key=RISK_ORDER.index)
