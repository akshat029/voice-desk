"""Backend selection and snapshot assembly.

Backends return elements with placeholder ids. The registry filters,
de-duplicates, and then numbers them in reading order, so the ids the model
sees are stable and predictable within a snapshot.
"""

from __future__ import annotations

import logging
import platform

from voicedesk.grounding.base import Element, ElementIndex, GroundingBackend

log = logging.getLogger(__name__)

_cached: GroundingBackend | None = None
_probed = False

# Rows within this many pixels of each other are treated as the same line
# when sorting into reading order.
ROW_TOLERANCE = 24


def _candidates() -> list[GroundingBackend]:
    from voicedesk.grounding.linux_atspi import LinuxAtSpiBackend
    from voicedesk.grounding.macos_ax import MacAxBackend
    from voicedesk.grounding.ocr_fallback import OcrBackend
    from voicedesk.grounding.windows_uia import WindowsUiaBackend

    native: dict[str, list[GroundingBackend]] = {
        "Windows": [WindowsUiaBackend()],
        "Darwin": [MacAxBackend()],
        "Linux": [LinuxAtSpiBackend()],
    }
    # OCR is always last. It is the universal fallback, but it only ever
    # produces text boxes: no roles, no enabled state, no way to invoke a
    # control without clicking it.
    return [*native.get(platform.system(), []), OcrBackend()]


def available_backends() -> list[str]:
    """Names of backends usable on this machine, best first."""
    return [backend.name for backend in _candidates() if backend.available()]


def get_backend(force: str | None = None) -> GroundingBackend | None:
    """Pick the best available backend, caching the probe result."""
    global _cached, _probed

    if force:
        for backend in _candidates():
            if backend.name == force:
                return backend if backend.available() else None
        return None

    if _probed:
        return _cached

    _probed = True
    for backend in _candidates():
        if backend.available():
            log.info("Grounding backend: %s", backend.name)
            _cached = backend
            return _cached

    log.warning("No grounding backend is available; falling back to coordinates.")
    _cached = None
    return None


def reset_backend_cache() -> None:
    global _cached, _probed
    _cached, _probed = None, False


def _dedupe(elements: list[Element]) -> list[Element]:
    """Collapse the same control appearing at several tree depths.

    UIA and AT-SPI both wrap real controls in containers that share the
    exact same bounds and name. Left in, the model sees the Send button
    four times with four different ids.
    """
    seen: dict[tuple, Element] = {}
    for element in elements:
        key = (element.role, element.name.strip().lower(), element.rect.center)
        current = seen.get(key)
        # Keep the deepest instance: that is the real leaf control rather
        # than a wrapper with identical bounds.
        if current is None or element.depth > current.depth:
            seen[key] = element
    return list(seen.values())


def _assign_ids(elements: list[Element]) -> list[Element]:
    """Number elements in reading order.

    Tree order is an implementation detail of the toolkit and jumps around
    the screen. Reading order matches how the user describes things, so
    "the second Save button" means something.
    """
    ordered = sorted(
        elements, key=lambda e: (e.rect.top // ROW_TOLERANCE, e.rect.left)
    )
    for index, element in enumerate(ordered, start=1):
        element.id = index
    return ordered


def snapshot(
    app_only: bool = True,
    max_elements: int = 200,
    force: str | None = None,
) -> ElementIndex:
    """Capture the current screen as an addressable element index.

    Never raises: grounding is an accuracy improvement, not a dependency.
    A failure returns an empty index and the caller falls back to
    coordinate clicking.
    """
    backend = get_backend(force)
    if backend is None:
        return ElementIndex([], backend="none")

    try:
        raw = backend.snapshot(app_only=app_only, max_elements=max_elements)
    except Exception as exc:
        log.warning("Grounding backend %s failed: %s", backend.name, exc)
        return ElementIndex([], backend=backend.name)

    return ElementIndex(_assign_ids(_dedupe(raw)), backend=backend.name)
