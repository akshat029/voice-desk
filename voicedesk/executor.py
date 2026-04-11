import platform
import subprocess
import time
from typing import Iterable

import pyautogui
import pyttsx3

from voicedesk.config import TTS_ENABLED

import logging


def _make_engine():
    """Create a fresh pyttsx3 engine with a female voice."""
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    for voice in voices:
        if "female" in voice.name.lower() or "zira" in voice.name.lower():
            engine.setProperty('voice', voice.id)
            break
    engine.setProperty('rate', 175)
    return engine


def speak_text(text: str) -> None:
    if not TTS_ENABLED or not text:
        return
    try:
        engine = _make_engine()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as exc:
        logging.error(f"TTS failed: {exc}")


def _numbers(action: dict, *keys: str) -> list[int | None]:
    values = []
    for key in keys:
        value = action.get(key)
        values.append(None if value is None else int(value))
    return values


def _press_many(keys: Iterable[str]) -> None:
    for key in keys:
        pyautogui.press(key)


def _open_app(name: str) -> None:
    if platform.system() == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
    else:
        subprocess.Popen(name.split(), shell=False)


def run_actions(actions: list[dict]) -> None:
    """Parse and execute a list of LLM-generated action dicts."""
    if not isinstance(actions, list):
        raise ValueError("Actions must be a list")
    for action in actions:
        kind = action.get("action")
        if not kind:
            continue
        x, y = _numbers(action, "x", "y")
        duration = float(action.get("duration", 0))
        if kind == "move":
            pyautogui.moveTo(x, y, duration=duration)
        elif kind == "click":
            pyautogui.click(x=x, y=y)
        elif kind == "double_click":
            pyautogui.doubleClick(x=x, y=y)
        elif kind == "right_click":
            pyautogui.rightClick(x=x, y=y)
        elif kind == "scroll":
            pyautogui.scroll(int(action.get("clicks", 0)), x=x, y=y)
        elif kind == "drag":
            dx, dy = _numbers(action, "dx", "dy")
            if x is not None and y is not None:
                pyautogui.dragTo(x, y, duration=duration or 0.2, button="left")
            else:
                pyautogui.drag(dx or 0, dy or 0, duration=duration or 0.2, button="left")
        elif kind == "type":
            pyautogui.write(str(action.get("text", "")), interval=0.01)
        elif kind == "press":
            keys = action.get("keys") or [action.get("text", "enter")]
            _press_many([str(key) for key in keys if key])
        elif kind == "hotkey":
            keys = [str(key) for key in action.get("keys", [])]
            if keys:
                pyautogui.hotkey(*keys)
        elif kind == "open_app":
            _open_app(str(action.get("name", "")))
        elif kind == "speak":
            speak_text(str(action.get("text", "")))
        elif kind == "wait":
            time.sleep(float(action.get("seconds", 1)))
        else:
            raise ValueError(f"Unsupported action: {kind}")
