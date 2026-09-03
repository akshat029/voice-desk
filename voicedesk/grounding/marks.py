"""Set-of-Marks overlay rendering.

Pairing a labelled screenshot with the numbered text list is what makes
element ids dependable. The model no longer has to translate a description
into coordinates; it reads a number off the image. Published results put
this well ahead of raw-pixel pointing, and it degrades gracefully because
the text list alone is still usable.
"""

from __future__ import annotations

import io
import logging

from voicedesk.grounding.base import Element

log = logging.getLogger(__name__)

# Cycled so adjacent boxes are visually separable.
PALETTE = (
    (255, 59, 48),
    (52, 199, 89),
    (0, 122, 255),
    (255, 149, 0),
    (175, 82, 222),
    (255, 214, 10),
)

BOX_WIDTH = 2
LABEL_PAD = 3


def annotate(
    image_bytes: bytes,
    elements: list[Element],
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    limit: int = 80,
) -> bytes:
    """Draw numbered boxes over the screenshot.

    ``scale_x`` and ``scale_y`` convert element rects from screen space
    into the coordinate space of ``image_bytes``, which is normally
    downscaled. Getting this backwards is the classic Set-of-Marks bug:
    labels drift off the controls they belong to.
    """
    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font()

    for index, element in enumerate(elements[:limit]):
        colour = PALETTE[index % len(PALETTE)]
        rect = element.rect.scaled(scale_x, scale_y)

        draw.rectangle(
            [rect.left, rect.top, rect.right, rect.bottom],
            outline=colour,
            width=BOX_WIDTH,
        )

        label = str(element.id)
        text_box = draw.textbbox((0, 0), label, font=font)
        text_w = text_box[2] - text_box[0]
        text_h = text_box[3] - text_box[1]

        # Prefer a badge above the box; drop it inside when the element is
        # flush against the top edge, which menu bars always are.
        badge_top = rect.top - text_h - LABEL_PAD * 2
        if badge_top < 0:
            badge_top = rect.top

        draw.rectangle(
            [
                rect.left,
                badge_top,
                rect.left + text_w + LABEL_PAD * 2,
                badge_top + text_h + LABEL_PAD * 2,
            ],
            fill=colour,
        )
        draw.text(
            (rect.left + LABEL_PAD, badge_top + LABEL_PAD),
            label,
            fill=(255, 255, 255),
            font=font,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _font():
    from PIL import ImageFont

    for candidate in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, 15)
        except Exception:
            continue
    return ImageFont.load_default()
