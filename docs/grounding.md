# UI grounding

## The problem this solves

Right now VoiceDesk shows the model a flat screenshot and asks it to return
pixel coordinates. That is the single largest source of silent failure in
the project, and no amount of prompt tuning fixes it.

A 24x24 toolbar icon occupies about 0.03% of a 1080p screen. The model has
to infer its centre from a downscaled image, and when it is twelve pixels
off the result is not an error: it is a click on whatever was next to the
thing you asked for. There is no feedback signal, so the assistant
confidently reports success.

Meanwhile, the operating system already knows the answer. Every desktop
platform publishes an accessibility tree that lists each control with its
role, its accessible name, its exact bounding box, and whether it is
enabled. Screen readers have depended on this for decades.

## The shift

Instead of asking "where should I click", we ask "which of these should I
click".

Before:

```json
{"action": "click", "x": 847, "y": 231}
```

After:

```json
{"action": "click_element", "element_id": 14}
```

The model picks a number from a list it can actually see. Coordinate
arithmetic moves into code, where it is deterministic and testable.

## Architecture

```
voicedesk/grounding/
  base.py           Element, Rect, ElementIndex, backend protocol
  registry.py       backend selection, dedupe, reading-order numbering
  windows_uia.py    Windows UI Automation      (draft, needs a Windows box)
  macos_ax.py       macOS AXUIElement          (stub, notes included)
  linux_atspi.py    Linux AT-SPI               (stub, notes included)
  ocr_fallback.py   Tesseract word boxes       (universal floor)
  marks.py          Set-of-Marks overlay renderer
```

Backends are probed best-first for the current platform and the native
accessibility API always wins. OCR is the fallback, because it yields text
boxes with no roles, no enabled state, and no way to activate a control
except by clicking it.

## Two grounding signals, used together

1. **A numbered text list** injected into the prompt:

   ```
   Interactive elements on screen (via uia):
   [1] menuitem "File"
   [2] menuitem "Edit"
   [7] edit "Search" (focused)
   [14] button "Send"
   [15] button "Discard" (disabled)
   ```

2. **A Set-of-Marks screenshot**, the same image with numbered boxes drawn
   over each element.

Either alone works. Together they are considerably more reliable, because
the model can cross-check the label it read against the box it can see.
The text list is also the cheap path: on a text-only backend such as Groq
it costs a few hundred tokens and no image upload at all, which is a
strict improvement over today's behaviour of computing a screenshot and
then discarding it.

## Invoking beats clicking

`ElementIndex.resolve(id).rect.center` gives a coordinate, so the existing
executor path keeps working unchanged. But where the backend supports it,
`backend.invoke(element)` is strictly better:

- it does not care whether the window is obscured or partially offscreen
- it does not race the UI, so a control that moved two pixels since the
  snapshot still activates
- it does not move the user's physical cursor
- it works on a locked or background window

`set_value` matters just as much for text fields. Typing into a search box
fights autocomplete, dropdown reordering, and debounced re-renders;
setting the value directly does not.

The fallback chain is: `invoke` -> coordinate click at the element centre
-> refuse and say so out loud.

## Adopting this in the main pipeline

Four changes, in order:

1. **`voicedesk/actions.py`** gains element-addressed variants alongside
   the coordinate ones, so nothing breaks while the tree coverage is still
   patchy:

   ```python
   class ClickElement(_Action):
       action: Literal["click_element"]
       element_id: int = Field(ge=1)

   class SetValue(_Action):
       action: Literal["set_value"]
       element_id: int = Field(ge=1)
       text: str
   ```

2. **`voicedesk/vision.py`** calls `grounding.snapshot()` and puts
   `index.to_prompt()` into the context dict, with the annotated image
   replacing the plain screenshot when a vision backend is active.

3. **`voicedesk/brain.py`** documents the two new actions and instructs
   the model to prefer them, falling back to coordinates only when the
   target is genuinely not in the list.

4. **`voicedesk/executor.py`** resolves `element_id` through the index,
   attempts `invoke`, and drops to a coordinate click if that returns
   False.

The executor needs the index that produced the ids, so it travels with the
plan exactly as `ScreenFrame` already does.

## Staleness

Element ids are valid only for the snapshot that produced them. A menu
that opens between snapshot and execution invalidates everything.

`ElementIndex.signature()` exists for this: re-snapshot immediately before
acting, compare signatures, and re-plan when they differ. That check is
also the natural place to hang the verify step of an observe-act-verify
loop, since "the UI changed in the way I expected" and "the UI changed
underneath me" are the same comparison read two ways.

## Known coverage gaps

Being honest about where this does not work:

- **Electron apps** (Slack, VS Code, Discord) expose a tree only once
  accessibility support is enabled, and the tree is often shallow.
- **Chrome** hides web content from UIA unless launched with
  `--force-renderer-accessibility` or a screen reader is detected.
- **Canvas and game UIs** (Figma, Photoshop, anything WebGL) publish
  nothing meaningful.
- **Wayland** restricts cross-application introspection and synthetic
  input far more aggressively than X11.

OCR covers the labelled cases in that list. For unlabelled icons, the next
step is a vision parser such as OmniParser, which detects interactable
regions from pixels and emits the same `Element` shape, so it slots in as
just another backend behind the same protocol.

## Latency budget

A full UIA walk of a complex app can take seconds, which is unacceptable
in a voice loop. Mitigations already in the code, and the ones still to
do:

- `SetGlobalSearchTimeout(0.5)` (done: without it, every property miss
  costs the default timeout)
- depth and visit caps (done: `MAX_DEPTH`, `MAX_VISITED`)
- focused window only by default rather than the whole desktop (done)
- cache per window handle and invalidate on foreground change (to do)
- snapshot speculatively while the user is still speaking (to do)

That last one is the real win: the snapshot can be warm before
transcription even finishes.
