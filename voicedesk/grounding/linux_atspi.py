"""Linux AT-SPI grounding backend.

STUB. The shape is settled; the implementation is not written.

To finish this:

1. Install the bindings: ``python3-pyatspi`` (or ``gi`` with the
   ``Atspi`` typelib). These are distro packages, not pip installs.
2. AT-SPI has to be switched on:
   ``gsettings set org.gnome.desktop.interface toolkit-accessibility true``.
   :meth:`available` should verify this instead of returning an empty tree.
3. Walk from ``pyatspi.Registry.getDesktop(0)`` down to the active
   application, then over each accessible's children, reading
   ``getRole()``, ``name``, ``getState()``, and
   ``queryComponent().getExtents(pyatspi.DESKTOP_COORDS)``.
4. Map roles: ROLE_PUSH_BUTTON -> button, ROLE_ENTRY / ROLE_TEXT -> edit,
   ROLE_CHECK_BOX -> checkbox, ROLE_MENU_ITEM -> menuitem, ROLE_LINK ->
   link.
5. Implement ``invoke`` via ``queryAction().doAction(0)`` and
   ``set_value`` via ``queryEditableText().setTextContents(text)``.

Two caveats worth recording: Wayland restricts both synthetic input and
cross-application introspection far more than X11, so coordinate clicking
may be blocked outright; and Qt applications need ``QT_ACCESSIBILITY=1``
before they publish anything.
"""

from __future__ import annotations

import logging
import platform

from voicedesk.grounding.base import Element

log = logging.getLogger(__name__)


class LinuxAtSpiBackend:
    name = "atspi"

    def available(self) -> bool:
        if platform.system() != "Linux":
            return False
        try:
            import pyatspi  # noqa: F401
        except Exception:
            return False
        return False  # flip to True once snapshot() is implemented

    def snapshot(self, app_only: bool = True, max_elements: int = 200) -> list[Element]:
        raise NotImplementedError("Linux AT-SPI backend is not implemented yet")

    def invoke(self, element: Element) -> bool:
        return False

    def set_value(self, element: Element, text: str) -> bool:
        return False
