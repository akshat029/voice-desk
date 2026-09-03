"""Screen capture, OCR, and coordinate mapping.

Two bugs lived here and both guaranteed misplaced clicks:

1. ``sct.monitors[0]`` is the *stitched* virtual desktop across every
   monitor. Its origin can be negative, so coordinates read off that image
   do not map into PyAutoGUI's space at all.
2. Nothing made the process DPI-aware, so ``mss`` captured physical pixels
   while PyAutoGUI acted on logical ones. At 150% Windows scaling that is a
   33% coordinate error on every single click.

Both are handled here, and every screenshot now travels with a
:class:`ScreenFrame` describing exactly how to map image coordinates back
onto the real screen.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import platform
import shutil
from dataclasses import dataclass
from typing import Any

import mss

import voicedesk.config as cfg

log = logging.getLogger(__name__)

_dpi_ready = False

# Commands that genuinely need pixels rather than text.
VISUAL_KEYWORDS = {
    "click",
    "double click",
    "right click",
    "drag",
    "drop",
    "scroll",
    "hover",
    "button",
    "icon",
    "checkbox",
    "dropdown",
    "toolbar",
    "highlighted",
    "on screen",
    "what do you see",
}

# Commands that reference screen content and so want OCR text, but not
# necessarily a full image. The old VISUAL_KEYWORDS list included bare
# words like "this", "that", "tab", and "select", which matched nearly
# every utterance and forced a full capture plus OCR every time.
SCREEN_REFERENCE_KEYWORDS = {
    "this",
    "that",
    "here",
    "there",
    "screen",
    "window",
    "page",
    "selected",
    "visible",
    "read",
    "summarize",
    "summarise",
    "what does",
    "what is on",
}

_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
)


def enable_dpi_awareness() -> None:
    """Make this process DPI-aware so capture and click spaces agree.

    Must run before PyAutoGUI first queries the screen size, which is why
    :mod:`voicedesk.executor` calls it at import time.
    """
    global _dpi_ready
    if _dpi_ready:
        return
    _dpi_ready = True
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        try:
            # 2 == PROCESS_PER_MONITOR_DPI_AWARE
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception as exc:  # pragma: no cover - platform specific
        log.warning("Could not enable DPI awareness: %s", exc)


def find_tesseract() -> str | None:
    """Locate the Tesseract binary, honouring ``TESSERACT_CMD``.

    The README claimed this happened. It never did: ``_extract_text``
    imported pytesseract but never assigned ``tesseract_cmd``, and the bare
    ``except Exception: return ""`` meant a missing binary looked identical
    to a blank screen.
    """
    if cfg.TESSERACT_CMD and os.path.isfile(cfg.TESSERACT_CMD):
        return cfg.TESSERACT_CMD
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _TESSERACT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class ScreenFrame:
    """Maps coordinates in a captured image back onto the real screen."""

    left: int
    top: int
    width: int
    height: int
    image_width: int
    image_height: int

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        scale_x = self.width / max(self.image_width, 1)
        scale_y = self.height / max(self.image_height, 1)
        return round(self.left + x * scale_x), round(self.top + y * scale_y)

    def describe(self) -> str:
        return (
            f"The screenshot is {self.image_width}x{self.image_height} px and "
            f"represents a {self.width}x{self.height} px display. Give all "
            f"coordinates in screenshot pixel space."
        )


def _pick_monitor(sct: Any) -> dict:
    index = cfg.CAPTURE_MONITOR
    monitors = sct.monitors
    if index < 1 or index >= len(monitors):
        index = 1 if len(monitors) > 1 else 0
    return monitors[index]


def capture() -> tuple[bytes, ScreenFrame]:
    """Grab the configured monitor, downscaled for the model."""
    enable_dpi_awareness()
    from PIL import Image

    with mss.mss() as sct:
        monitor = _pick_monitor(sct)
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)

    full_w, full_h = image.size
    limit = cfg.MAX_SCREENSHOT_DIM
    if limit and max(full_w, full_h) > limit:
        ratio = limit / max(full_w, full_h)
        image = image.resize(
            (max(1, int(full_w * ratio)), max(1, int(full_h * ratio))),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)

    frame = ScreenFrame(
        left=int(monitor["left"]),
        top=int(monitor["top"]),
        width=int(monitor["width"]),
        height=int(monitor["height"]),
        image_width=image.size[0],
        image_height=image.size[1],
    )
    return buffer.getvalue(), frame


def extract_text(image_bytes: bytes) -> str:
    """OCR a screenshot. Failures are logged, never silently swallowed."""
    if not cfg.OCR_ENABLED:
        return ""
    binary = find_tesseract()
    if binary is None:
        log.warning("OCR skipped: Tesseract binary not found.")
        return ""
    try:
        import pytesseract
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = binary
        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
        return " ".join(text.split())[: cfg.MAX_OCR_CHARS]
    except Exception as exc:
        log.warning("OCR failed: %s", exc)
        return ""


def active_window_title() -> str:
    """Best-effort focused window title. Empty string when unavailable."""
    try:
        import pyautogui

        getter = getattr(pyautogui, "getActiveWindowTitle", None)
        if callable(getter):
            return str(getter() or "")
    except Exception:  # pragma: no cover - platform specific
        pass
    return ""


def needs_pixels(command_text: str) -> bool:
    lowered = command_text.lower()
    return any(keyword in lowered for keyword in VISUAL_KEYWORDS)


def needs_screen_text(command_text: str) -> bool:
    lowered = command_text.lower()
    return any(keyword in lowered for keyword in SCREEN_REFERENCE_KEYWORDS)


def get_context(command_text: str) -> dict[str, Any]:
    """Assemble screen context, doing only the work this command needs.

    The old ``get_context`` captured *and* OCR'd the full screen on every
    command: one to three seconds of Tesseract before the model was even
    called. On the Groq backend the screenshot was then discarded, because
    ``supports_vision()`` was False.
    """
    context: dict[str, Any] = {
        "active_window": active_window_title(),
        "platform": platform.system(),
    }

    wants_pixels = needs_pixels(command_text)
    wants_text = cfg.OCR_ENABLED and (wants_pixels or needs_screen_text(command_text))
    if not wants_pixels and not wants_text:
        return context

    image_bytes, frame = capture()
    context["frame"] = frame
    context["screen_size"] = f"{frame.width}x{frame.height}"

    if wants_text:
        context["screen_text"] = extract_text(image_bytes)
    if wants_pixels and cfg.supports_vision():
        context["screenshot_base64"] = base64.b64encode(image_bytes).decode("ascii")
        context["frame_note"] = frame.describe()

    return context
