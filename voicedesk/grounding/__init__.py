"""UI grounding: address elements by identity instead of pixel guesses.

The rest of VoiceDesk asks a model to look at a flat screenshot and invent
coordinates. That approach has a hard accuracy ceiling: a 24x24 close
button is roughly 0.03% of a 1080p screen, and being twelve pixels off is
indistinguishable from being right until something wrong happens.

Every desktop OS already publishes an accessibility tree that lists each
control, its role, its accessible name, its bounding box, and whether it is
enabled. Reading that tree turns the hardest part of the problem, "where is
the Send button", into a lookup.

Usage sketch::

    from voicedesk.grounding import snapshot

    index = snapshot()
    print(index.to_prompt())      # numbered element list for the model
    element = index.resolve(14)   # model replied with element_id 14
    x, y = element.rect.center
"""

from voicedesk.grounding.base import (
    Element,
    ElementIndex,
    GroundingBackend,
    Rect,
    UnknownElement,
)
from voicedesk.grounding.registry import available_backends, get_backend, snapshot

__all__ = [
    "Element",
    "ElementIndex",
    "GroundingBackend",
    "Rect",
    "UnknownElement",
    "available_backends",
    "get_backend",
    "snapshot",
]
