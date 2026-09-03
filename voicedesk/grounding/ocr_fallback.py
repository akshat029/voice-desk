"""OCR grounding fallback.

When an application exposes no usable accessibility tree, OCR word boxes
are still better than nothing: they give real bounding boxes for visible
text, so "click Sign In" becomes a lookup rather than a guess.

Limits worth being honest about: no roles, no enabled state, no way to
invoke a control except by clicking it, and icons without labels are
invisible. This is a floor, not a solution.
"""

from __future__ import annotations

import logging

from voicedesk.grounding.base import Element, Rect

log = logging.getLogger(__name__)

# Tesseract emits a confidence per word. Below this it is usually noise
# from window chrome, gradients, or antialiasing.
MIN_CONFIDENCE = 55.0

# Words closer than this horizontally are joined into one phrase, so
# "Sign" and "In" become a single clickable target.
WORD_GAP = 14


class OcrBackend:
    name = "ocr"

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401

            from voicedesk.vision import find_tesseract
        except Exception:
            return False
        return find_tesseract() is not None

    def snapshot(self, app_only: bool = True, max_elements: int = 200) -> list[Element]:
        del app_only  # OCR cannot distinguish windows

        import io

        import pytesseract
        from PIL import Image

        from voicedesk.vision import capture, find_tesseract

        binary = find_tesseract()
        if binary is None:
            return []
        pytesseract.pytesseract.tesseract_cmd = binary

        image_bytes, frame = capture()
        image = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )

        words = self._words(data)
        phrases = self._group(words)

        elements: list[Element] = []
        for text, rect in phrases[:max_elements]:
            # Rects come back in screenshot space; the frame maps them onto
            # the real display, accounting for downscale and monitor origin.
            left, top = frame.to_screen(rect.left, rect.top)
            right, bottom = frame.to_screen(rect.right, rect.bottom)
            elements.append(
                Element(
                    id=-1,
                    role="text",
                    name=text,
                    rect=Rect(left, top, right - left, bottom - top),
                    source=self.name,
                    depth=0,
                )
            )
        return elements

    def invoke(self, element: Element) -> bool:
        # OCR has no handle on the control, only its location.
        return False

    def set_value(self, element: Element, text: str) -> bool:
        return False

    # -- grouping -------------------------------------------------------

    @staticmethod
    def _words(data: dict) -> list[tuple[str, Rect, tuple]]:
        results: list[tuple[str, Rect, tuple]] = []
        count = len(data.get("text", []))
        for index in range(count):
            text = str(data["text"][index]).strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence < MIN_CONFIDENCE:
                continue
            rect = Rect(
                int(data["left"][index]),
                int(data["top"][index]),
                int(data["width"][index]),
                int(data["height"][index]),
            )
            line = (
                data.get("block_num", [0] * count)[index],
                data.get("par_num", [0] * count)[index],
                data.get("line_num", [0] * count)[index],
            )
            results.append((text, rect, line))
        return results

    @staticmethod
    def _group(words: list[tuple[str, Rect, tuple]]) -> list[tuple[str, Rect]]:
        """Join adjacent words on the same line into phrases.

        Individual words are poor click targets. A button labelled
        "Sign In" should be one element, not two.
        """
        by_line: dict[tuple, list[tuple[str, Rect]]] = {}
        for text, rect, line in words:
            by_line.setdefault(line, []).append((text, rect))

        phrases: list[tuple[str, Rect]] = []
        for entries in by_line.values():
            entries.sort(key=lambda item: item[1].left)
            current_text: list[str] = []
            current: Rect | None = None

            for text, rect in entries:
                if current is None:
                    current_text, current = [text], rect
                    continue
                if rect.left - current.right <= WORD_GAP:
                    current_text.append(text)
                    current = Rect(
                        current.left,
                        min(current.top, rect.top),
                        rect.right - current.left,
                        max(current.bottom, rect.bottom) - min(current.top, rect.top),
                    )
                else:
                    phrases.append((" ".join(current_text), current))
                    current_text, current = [text], rect

            if current is not None:
                phrases.append((" ".join(current_text), current))

        return phrases
