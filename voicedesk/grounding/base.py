"""Element model shared by every grounding backend."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

# Roles the model can usefully act on. Everything else is layout noise and
# is filtered out before the element list reaches the prompt.
ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "edit",
    "link",
    "listitem",
    "menuitem",
    "radio",
    "slider",
    "splitbutton",
    "tab",
    "treeitem",
}

# Roles kept for context even though they are not clickable.
CONTEXT_ROLES = {"text", "document", "heading", "statusbar", "title"}


class UnknownElement(KeyError):
    """The model referenced an element id that is not in the current index."""


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    @property
    def area(self) -> int:
        return max(self.width, 0) * max(self.height, 0)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def offset(self, dx: int, dy: int) -> Rect:
        return Rect(self.left + dx, self.top + dy, self.width, self.height)

    def scaled(self, scale_x: float, scale_y: float) -> Rect:
        return Rect(
            round(self.left * scale_x),
            round(self.top * scale_y),
            round(self.width * scale_x),
            round(self.height * scale_y),
        )

    def is_plausible(self, screen_w: int, screen_h: int) -> bool:
        """Reject the degenerate boxes accessibility trees love to emit.

        Offscreen controls, zero-area rects, and full-screen container
        bounds are all common and all useless as click targets.
        """
        if self.width <= 0 or self.height <= 0:
            return False
        if self.right <= 0 or self.bottom <= 0:
            return False
        if self.width >= screen_w and self.height >= screen_h:
            return False
        return True


@dataclass
class Element:
    """One interactive thing on screen, addressed by id rather than pixels."""

    id: int
    role: str
    name: str
    rect: Rect
    enabled: bool = True
    focused: bool = False
    value: str = ""
    source: str = "unknown"
    app: str = ""
    depth: int = 0
    native: object | None = field(default=None, repr=False, compare=False)

    @property
    def is_actionable(self) -> bool:
        return self.enabled and self.role in ACTIONABLE_ROLES

    @property
    def label(self) -> str:
        return self.name or self.value or f"<{self.role}>"

    def to_prompt_line(self) -> str:
        """One line of the numbered list handed to the model."""
        parts = [f"[{self.id}]", self.role]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.value and self.value != self.name:
            parts.append(f"value={self.value[:40]!r}")
        flags = []
        if not self.enabled:
            flags.append("disabled")
        if self.focused:
            flags.append("focused")
        if flags:
            parts.append(f"({', '.join(flags)})")
        return " ".join(parts)


@runtime_checkable
class GroundingBackend(Protocol):
    """A platform-specific source of on-screen elements."""

    name: str

    def available(self) -> bool:
        """Whether this backend can run here, with no side effects."""

    def snapshot(self, app_only: bool = True, max_elements: int = 200) -> list[Element]:
        """Return the currently visible elements, outermost first."""

    def invoke(self, element: Element) -> bool:
        """Activate an element through the accessibility API.

        Far more reliable than synthesising a click, because it does not
        depend on the window being unobscured or the pointer landing in the
        right place. Returns False when the backend cannot do it, so the
        caller can fall back to a coordinate click.
        """

    def set_value(self, element: Element, text: str) -> bool:
        """Set a text field's value directly rather than typing into it."""


class ElementIndex:
    """An addressable snapshot of the screen.

    Ids are assigned per snapshot and are only valid until the UI changes,
    which is why :meth:`signature` exists: an agent loop should re-snapshot
    and compare before trusting an id it decided on earlier.
    """

    def __init__(self, elements: Iterable[Element], backend: str = "unknown") -> None:
        self.elements: list[Element] = list(elements)
        self.backend = backend
        self._by_id = {element.id: element for element in self.elements}

    def __len__(self) -> int:
        return len(self.elements)

    def __iter__(self):
        return iter(self.elements)

    @property
    def actionable(self) -> list[Element]:
        return [element for element in self.elements if element.is_actionable]

    def resolve(self, element_id: int) -> Element:
        try:
            return self._by_id[int(element_id)]
        except (KeyError, TypeError, ValueError) as exc:
            raise UnknownElement(
                f"element {element_id!r} is not in this snapshot; re-snapshot first"
            ) from exc

    def point(self, element_id: int) -> tuple[int, int]:
        return self.resolve(element_id).rect.center

    def find(self, name: str, role: str | None = None, cutoff: float = 0.6):
        """Fuzzy-match an element by accessible name.

        Speech recognition mangles labels constantly, so exact matching is
        not an option: "click sign in" has to find "Sign In".
        """
        candidates = [
            element
            for element in self.elements
            if role is None or element.role == role
        ]
        if not candidates:
            return None

        wanted = name.strip().lower()
        for element in candidates:
            if element.name.strip().lower() == wanted:
                return element

        names = [element.name.strip().lower() for element in candidates]
        matches = difflib.get_close_matches(wanted, names, n=1, cutoff=cutoff)
        if not matches:
            return None
        return candidates[names.index(matches[0])]

    def to_prompt(self, limit: int = 80, actionable_only: bool = True) -> str:
        """Render the numbered element list for the model.

        This replaces "guess the coordinates from this screenshot" with
        "pick a number", which is a task language models are reliable at.
        """
        source = self.actionable if actionable_only else self.elements
        if not source:
            return "No interactive elements were detected."
        lines = [element.to_prompt_line() for element in source[:limit]]
        header = f"Interactive elements on screen (via {self.backend}):"
        if len(source) > limit:
            lines.append(f"... and {len(source) - limit} more")
        return header + chr(10) + chr(10).join(lines)

    def signature(self) -> tuple:
        """Cheap fingerprint for detecting that the UI moved under us."""
        return tuple(
            (element.role, element.name, element.rect.center)
            for element in self.elements[:60]
        )
