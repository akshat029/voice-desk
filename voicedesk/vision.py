import base64
import io
from typing import Any

import mss
import mss.tools

from voicedesk.config import MAX_OCR_CHARS, OCR_ENABLED

VISUAL_KEYWORDS = {
    "click",
    "double click",
    "right click",
    "drag",
    "drop",
    "scroll",
    "hover",
    "select",
    "button",
    "icon",
    "menu",
    "tab",
    "this",
    "that",
    "here",
    "there",
}


def _capture_png_bytes() -> bytes:
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        return mss.tools.to_png(shot.rgb, shot.size)


def _extract_text(image_bytes: bytes) -> str:
    if not OCR_ENABLED:
        return ""
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
        return " ".join(text.split())[:MAX_OCR_CHARS]
    except Exception:
        return ""


def _needs_screenshot(command_text: str, screen_text: str) -> bool:
    lowered = command_text.lower()
    if any(keyword in lowered for keyword in VISUAL_KEYWORDS):
        return True
    return not bool(screen_text)


def get_context(command_text: str) -> dict[str, Any]:
    image_bytes = _capture_png_bytes()
    screen_text = _extract_text(image_bytes)
    context: dict[str, Any] = {"screen_text": screen_text}
    if _needs_screenshot(command_text, screen_text):
        context["screenshot_base64"] = base64.b64encode(image_bytes).decode("ascii")
    return context
