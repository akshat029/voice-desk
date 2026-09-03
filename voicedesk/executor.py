"""Performs validated actions. Nothing here trusts the model.

Actions arrive as parsed :mod:`voicedesk.actions` objects, so this module
never has to guess at types or handle missing coordinates: an invalid plan
is rejected before execution starts.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading
import time

import voicedesk.config as cfg
from voicedesk.actions import Action, Risk
from voicedesk.vision import ScreenFrame, enable_dpi_awareness

log = logging.getLogger(__name__)

# DPI awareness has to be set before PyAutoGUI caches the screen size.
enable_dpi_awareness()

import pyautogui  # noqa: E402

pyautogui.FAILSAFE = True
# Small settle time between actions. Left unset, PyAutoGUI's own default
# applies inconsistently and fast plans race the UI they are driving.
pyautogui.PAUSE = 0.05

FailSafe = pyautogui.FailSafeException


class ExecutionError(RuntimeError):
    pass


class AppNotAllowed(ExecutionError):
    """An ``open_app`` target was not on the allowlist."""


# -- text to speech -----------------------------------------------------

_engine = None
_engine_lock = threading.Lock()


def _engine_instance():
    """One engine, reused.

    ``pyttsx3.init()`` was previously called for every utterance. That
    re-enumerates SAPI voices and leaks COM objects, and is a well known
    cause of the engine hanging after repeated calls.
    """
    global _engine
    if _engine is not None:
        return _engine

    import pyttsx3

    engine = pyttsx3.init()
    hint = cfg.TTS_VOICE_HINT.lower()
    if hint:
        for voice in engine.getProperty("voices"):
            if hint in str(voice.name).lower():
                engine.setProperty("voice", voice.id)
                break
    engine.setProperty("rate", cfg.TTS_RATE)
    _engine = engine
    return _engine


def speak_text(text: str) -> None:
    if not cfg.TTS_ENABLED or not text:
        return
    try:
        with _engine_lock:
            engine = _engine_instance()
            engine.say(text)
            engine.runAndWait()
    except Exception as exc:
        log.error("TTS failed: %s", exc)


# -- app launching ------------------------------------------------------

_APP_TARGETS: dict[str, dict[str, str]] = {
    "chrome": {
        "Windows": "chrome",
        "Darwin": "Google Chrome",
        "Linux": "google-chrome",
    },
    "firefox": {"Windows": "firefox", "Darwin": "Firefox", "Linux": "firefox"},
    "msedge": {
        "Windows": "msedge",
        "Darwin": "Microsoft Edge",
        "Linux": "microsoft-edge",
    },
    "code": {
        "Windows": "code",
        "Darwin": "Visual Studio Code",
        "Linux": "code",
    },
    "notepad": {"Windows": "notepad", "Darwin": "TextEdit", "Linux": "gedit"},
    "calc": {
        "Windows": "calc",
        "Darwin": "Calculator",
        "Linux": "gnome-calculator",
    },
    "explorer": {"Windows": "explorer", "Darwin": "Finder", "Linux": "nautilus"},
    "spotify": {"Windows": "spotify", "Darwin": "Spotify", "Linux": "spotify"},
    "slack": {"Windows": "slack", "Darwin": "Slack", "Linux": "slack"},
    "notion": {"Windows": "notion", "Darwin": "Notion", "Linux": "notion-app"},
    "terminal": {
        "Windows": "wt",
        "Darwin": "Terminal",
        "Linux": "gnome-terminal",
    },
}


def resolve_app(name: str) -> str:
    """Map a friendly app name to a launch target, or refuse.

    The old ``_open_app`` handed an LLM-controlled string straight to
    ``Popen``. On POSIX it ran ``name.split()``, which is arbitrary command
    execution; on Windows ``cmd /c start "" <name>`` is nearly as bad. And
    because OCR text from the screen was injected into the prompt, anything
    that could put text on the user's display could reach it. ``open_app``
    was not even in the old dangerous-actions set, so it never prompted.
    """
    key = name.strip().lower()
    if key not in cfg.APP_ALLOWLIST:
        raise AppNotAllowed(
            f"{name!r} is not in APP_ALLOWLIST. Add it to .env to permit it."
        )
    targets = _APP_TARGETS.get(key)
    if not targets:
        raise AppNotAllowed(f"No launch target is registered for {name!r}.")
    target = targets.get(platform.system())
    if not target:
        raise AppNotAllowed(f"{name!r} is not mapped for {platform.system()}.")
    return target


def open_app(name: str) -> None:
    target = resolve_app(name)
    system = platform.system()
    log.info("Launching %s -> %s", name, target)
    if system == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
    elif system == "Darwin":
        subprocess.Popen(["open", "-a", target], shell=False)
    else:
        if shutil.which(target) is None:
            raise AppNotAllowed(f"{target!r} is not installed on this system.")
        subprocess.Popen([target], shell=False)


# -- dispatch -----------------------------------------------------------


def _point(action, frame: ScreenFrame | None) -> tuple[int, int]:
    """Translate model coordinates into screen coordinates."""
    if frame is None:
        return int(action.x), int(action.y)
    return frame.to_screen(action.x, action.y)


def run_actions(actions: list[Action], frame: ScreenFrame | None = None) -> None:
    for action in actions:
        if cfg.DRY_RUN and action.risk is not Risk.READ:
            log.info("[dry-run] would %s", action.describe())
            continue
        log.info("Executing: %s", action.describe())
        run_one(action, frame)


def run_one(action: Action, frame: ScreenFrame | None = None) -> None:
    kind = action.action

    if kind == "speak":
        speak_text(action.text)  # type: ignore[attr-defined]
        return
    if kind == "wait":
        time.sleep(action.seconds)  # type: ignore[attr-defined]
        return
    if kind == "open_app":
        open_app(action.name)  # type: ignore[attr-defined]
        return
    if kind == "type":
        pyautogui.write(action.text, interval=0.01)  # type: ignore[attr-defined]
        return
    if kind == "press":
        for key in action.keys:  # type: ignore[attr-defined]
            pyautogui.press(key)
        return
    if kind == "hotkey":
        pyautogui.hotkey(*action.keys)  # type: ignore[attr-defined]
        return

    x, y = _point(action, frame)
    if kind == "move":
        pyautogui.moveTo(x, y, duration=action.duration)  # type: ignore[attr-defined]
    elif kind == "click":
        pyautogui.click(x=x, y=y)
    elif kind == "double_click":
        pyautogui.doubleClick(x=x, y=y)
    elif kind == "right_click":
        pyautogui.rightClick(x=x, y=y)
    elif kind == "scroll":
        pyautogui.scroll(action.clicks, x=x, y=y)  # type: ignore[attr-defined]
    elif kind == "drag":
        pyautogui.dragTo(x, y, duration=action.duration or 0.2, button="left")  # type: ignore[attr-defined]
    else:  # pragma: no cover - the schema makes this unreachable
        raise ExecutionError(f"Unsupported action: {kind}")
