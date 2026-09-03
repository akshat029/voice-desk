"""macOS Accessibility (AXUIElement) grounding backend.

STUB. The shape is settled; the implementation is not written.

To finish this:

1. ``pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices``
2. VoiceDesk must be granted Accessibility permission under
   System Settings > Privacy and Security > Accessibility. Without it
   every AX call returns an error rather than an empty tree, so
   :meth:`available` has to check ``AXIsProcessTrusted()`` and say so.
3. Get the frontmost app with
   ``NSWorkspace.sharedWorkspace().frontmostApplication()``, then
   ``AXUIElementCreateApplication(pid)``.
4. Walk ``kAXChildrenAttribute``, reading ``kAXRoleAttribute``,
   ``kAXTitleAttribute``, ``kAXValueAttribute``, ``kAXEnabledAttribute``,
   ``kAXPositionAttribute``, and ``kAXSizeAttribute``.
5. Map AX roles onto our vocabulary: AXButton -> button, AXTextField ->
   edit, AXCheckBox -> checkbox, AXMenuItem -> menuitem, AXLink -> link.
6. Implement ``invoke`` via ``AXUIElementPerformAction`` with
   ``kAXPressAction``, and ``set_value`` via ``AXUIElementSetAttributeValue``
   on ``kAXValueAttribute``.

One macOS-specific trap: AX positions are in a top-left origin screen
space, but several Cocoa APIs are bottom-left. Mixing them produces
vertically mirrored coordinates that look plausible on a centred window
and are completely wrong elsewhere.
"""

from __future__ import annotations

import logging
import platform

from voicedesk.grounding.base import Element

log = logging.getLogger(__name__)


class MacAxBackend:
    name = "ax"

    def available(self) -> bool:
        if platform.system() != "Darwin":
            return False
        try:
            from ApplicationServices import AXIsProcessTrusted
        except Exception:
            return False
        if not AXIsProcessTrusted():
            log.warning(
                "Accessibility permission is not granted, so the macOS "
                "element tree is unreadable. Grant it under System Settings "
                "> Privacy and Security > Accessibility."
            )
            return False
        return False  # flip to True once snapshot() is implemented

    def snapshot(self, app_only: bool = True, max_elements: int = 200) -> list[Element]:
        raise NotImplementedError("macOS AX backend is not implemented yet")

    def invoke(self, element: Element) -> bool:
        return False

    def set_value(self, element: Element, text: str) -> bool:
        return False
