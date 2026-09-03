"""Windows UI Automation grounding backend.

Requires the ``uiautomation`` package, which wraps the COM UIA client::

    pip install uiautomation

DRAFT: this needs validating on a real Windows desktop against real
applications. Electron apps (Slack, VS Code, Discord) in particular expose
their tree only after accessibility support is switched on, and Chrome
needs the --force-renderer-accessibility flag or a screen reader present
before web content appears at all. Where the tree is empty, the OCR
fallback still applies.
"""

from __future__ import annotations

import logging
import platform

from voicedesk.grounding.base import CONTEXT_ROLES, Element, Rect

log = logging.getLogger(__name__)

# UIA ControlType names mapped onto our neutral role vocabulary.
ROLE_MAP = {
    "ButtonControl": "button",
    "CheckBoxControl": "checkbox",
    "ComboBoxControl": "combobox",
    "DocumentControl": "document",
    "EditControl": "edit",
    "HeaderItemControl": "heading",
    "HyperlinkControl": "link",
    "ListItemControl": "listitem",
    "MenuItemControl": "menuitem",
    "RadioButtonControl": "radio",
    "SliderControl": "slider",
    "SplitButtonControl": "splitbutton",
    "StatusBarControl": "statusbar",
    "TabItemControl": "tab",
    "TextControl": "text",
    "TitleBarControl": "title",
    "TreeItemControl": "treeitem",
}

# Walking the entire tree of a complex app costs seconds. These caps keep a
# snapshot inside a latency budget a voice assistant can live with.
MAX_DEPTH = 14
MAX_VISITED = 3000


class WindowsUiaBackend:
    name = "uia"

    def available(self) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import uiautomation  # noqa: F401
        except Exception:
            return False
        return True

    # -- capture --------------------------------------------------------

    def snapshot(self, app_only: bool = True, max_elements: int = 200) -> list[Element]:
        import uiautomation as auto

        # Without this, every miss costs the default search timeout and a
        # snapshot takes tens of seconds.
        auto.SetGlobalSearchTimeout(0.5)

        root = self._root(auto, app_only)
        if root is None:
            return []

        app_name = self._safe(lambda: root.Name) or ""
        screen_w, screen_h = auto.GetScreenSize()

        elements: list[Element] = []
        visited = 0
        # Explicit stack rather than recursion: these trees can be deep
        # and malformed, and a RecursionError mid-walk loses everything.
        stack: list[tuple[object, int]] = [(root, 0)]

        while stack and len(elements) < max_elements and visited < MAX_VISITED:
            node, depth = stack.pop()
            visited += 1

            element = self._to_element(node, depth, app_name, screen_w, screen_h)
            if element is not None:
                elements.append(element)

            if depth >= MAX_DEPTH:
                continue

            children = self._safe(lambda: node.GetChildren()) or []
            # Reversed, so popping yields the original document order.
            for child in reversed(children):
                stack.append((child, depth + 1))

        if visited >= MAX_VISITED:
            log.debug("UIA walk hit the visit cap; element list may be partial.")
        return elements

    def _root(self, auto, app_only: bool):
        if not app_only:
            return self._safe(lambda: auto.GetRootControl())
        focused = self._safe(lambda: auto.GetFocusedControl())
        if focused is not None:
            top = self._safe(lambda: focused.GetTopLevelControl())
            if top is not None:
                return top
        return self._safe(lambda: auto.GetForegroundControl()) or self._safe(
            lambda: auto.GetRootControl()
        )

    def _to_element(
        self, node, depth: int, app_name: str, screen_w: int, screen_h: int
    ) -> Element | None:
        control_type = self._safe(lambda: node.ControlTypeName) or ""
        role = ROLE_MAP.get(control_type)
        if role is None:
            return None

        if self._safe(lambda: node.IsOffscreen):
            return None

        bounds = self._safe(lambda: node.BoundingRectangle)
        if bounds is None:
            return None

        rect = Rect(
            left=int(bounds.left),
            top=int(bounds.top),
            width=int(bounds.right - bounds.left),
            height=int(bounds.bottom - bounds.top),
        )
        if not rect.is_plausible(screen_w, screen_h):
            return None

        name = (self._safe(lambda: node.Name) or "").strip()
        value = ""
        if role in {"edit", "combobox"}:
            value = (self._safe(lambda: node.GetValuePattern().Value) or "").strip()

        # An unnamed, valueless control is unaddressable: the model has
        # nothing to refer to it by. Context roles are the exception,
        # since their text content is the point.
        if not name and not value and role not in CONTEXT_ROLES:
            return None

        return Element(
            id=-1,  # assigned by the registry in reading order
            role=role,
            name=name[:120],
            rect=rect,
            enabled=bool(self._safe(lambda: node.IsEnabled) is not False),
            focused=bool(self._safe(lambda: node.HasKeyboardFocus)),
            value=value[:200],
            source=self.name,
            app=app_name[:80],
            depth=depth,
            native=node,
        )

    # -- interaction ----------------------------------------------------

    def invoke(self, element: Element) -> bool:
        """Activate through UIA instead of synthesising a click.

        This is the real prize. An Invoke call does not care whether the
        window is obscured, whether the pointer arrives, or whether the
        control moved two pixels since the screenshot.
        """
        node = element.native
        if node is None:
            return False
        for attempt in (
            lambda: node.GetInvokePattern().Invoke(),
            lambda: node.GetTogglePattern().Toggle(),
            lambda: node.GetSelectionItemPattern().Select(),
            lambda: node.GetExpandCollapsePattern().Expand(),
        ):
            try:
                attempt()
                return True
            except Exception:
                continue
        return False

    def set_value(self, element: Element, text: str) -> bool:
        """Set a field directly, so autocomplete cannot eat the keystrokes."""
        node = element.native
        if node is None:
            return False
        try:
            node.GetValuePattern().SetValue(text)
            return True
        except Exception:
            return False

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _safe(getter):
        """UIA property reads raise COM errors on any transient UI change.

        A window closing mid-walk is normal, not exceptional, so every
        read is individually guarded.
        """
        try:
            return getter()
        except Exception:
            return None
