"""VoiceDesk entry point: listen, plan, gate, execute."""

from __future__ import annotations

import logging
import re
import sys
import time

import voicedesk.config as cfg
from voicedesk.actions import Action, PlanError, Risk
from voicedesk.brain import BrainError, plan_actions, reset_history
from voicedesk.executor import AppNotAllowed, FailSafe, run_actions, speak_text
from voicedesk.listener import MicError, listen_forever, listen_once
from voicedesk.preflight import PreflightError, check_llm, run_preflight
from voicedesk.vision import enable_dpi_awareness, get_context

log = logging.getLogger(__name__)

AFFIRMATIVE = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "proceed",
    "confirm",
    "confirmed",
    "affirmative",
    "ok",
    "okay",
    "go",
    "do",
    "continue",
}

NEGATIVE = {
    "no",
    "nope",
    "nah",
    "stop",
    "cancel",
    "dont",
    "don",
    "abort",
    "wait",
    "never",
    "negative",
}

_WORDS = re.compile(r"[a-z]+")

_SHELL_WINDOW = re.compile(
    r"(command prompt|powershell|windows terminal|cmd\.exe|terminal|iterm|bash|zsh)",
    re.IGNORECASE,
)

_BACKEND_PHRASES = {
    "gemini": ("switch to gemini", "use gemini"),
    "groq": ("switch to groq", "use groq"),
    "ollama": ("switch to ollama", "use ollama", "go local", "go private"),
}


def parse_confirmation(response: str) -> bool:
    """Word-boundary confirmation parsing, with negation taking priority.

    The old check was a substring scan over a phrase set that included
    "do it", so "no, don't do it" *contained* "do it" and was read as
    consent. "ok" also matched inside unrelated words like "spoke", "look",
    and "broke".
    """
    words = set(_WORDS.findall(response.lower()))
    if not words:
        return False
    if words & NEGATIVE:
        return False
    return bool(words & AFFIRMATIVE)


def effective_risk(action: Action, active_window: str = "") -> Risk:
    """Escalate risk based on where the action will land.

    Typing is normally harmless, but typing into a shell is how a typo
    becomes a destroyed working directory. The old ``_DANGEROUS_ACTIONS``
    set contained only "drag", leaving both `type` and `open_app`
    completely unguarded.
    """
    if action.action == "type" and _SHELL_WINDOW.search(active_window or ""):
        return Risk.DESTRUCTIVE
    if action.action == "open_app":
        name = action.name.strip().lower()  # type: ignore[attr-defined]
        if name in cfg.SHELL_APPS:
            return Risk.DESTRUCTIVE
    return action.risk


def _confirm(action: Action) -> bool:
    speak_text(f"I'm about to {action.describe()}. Should I go ahead?")
    reply = listen_once(timeout_seconds=cfg.CONFIRM_TIMEOUT)
    if cfg.LOG_TRANSCRIPTS:
        log.info("Confirmation reply: %r", reply)
    approved = parse_confirmation(reply)
    log.info(
        "Confirmation for %r: %s",
        action.describe(),
        "approved" if approved else "declined",
    )
    return approved


def _maybe_switch_backend(command_text: str) -> bool:
    """Handle voice backend switching, validating the target first."""
    lowered = command_text.lower()
    for backend, phrases in _BACKEND_PHRASES.items():
        if not any(phrase in lowered for phrase in phrases):
            continue

        previous = cfg.LLM_BACKEND
        cfg.LLM_BACKEND = backend
        blockers = [problem for problem in check_llm() if problem.fatal]
        if blockers:
            cfg.LLM_BACKEND = previous
            log.warning("Backend switch to %s refused: %s", backend, blockers[0].what)
            speak_text(f"I can't switch to {backend}. {blockers[0].fix}")
            return True

        # Message shapes differ per backend, notably Gemini's strict role
        # alternation, so carrying history across a switch is unsafe.
        reset_history()
        log.info("Backend switched to %s -> %s", backend.upper(), cfg.active_model())
        speak_text(f"Switched to {backend}.")
        return True
    return False


def handle_command(command_text: str) -> None:
    if cfg.LOG_TRANSCRIPTS:
        log.info("Heard: %r", command_text)
    else:
        log.info("Heard a command (%d chars)", len(command_text))

    if _maybe_switch_backend(command_text):
        return

    started = time.perf_counter()
    try:
        context = get_context(command_text)
        actions = plan_actions(command_text, context)
        if not actions:
            raise PlanError("the model returned an empty plan")

        log.info(
            "Planned %d action(s) in %.1fs",
            len(actions),
            time.perf_counter() - started,
        )

        active_window = str(context.get("active_window", ""))
        for action in actions:
            risk = effective_risk(action, active_window)
            if cfg.CONFIRM_DANGEROUS and risk is Risk.DESTRUCTIVE:
                if not _confirm(action):
                    # Abandon the whole plan. Skipping one step and
                    # continuing leaves the desktop half-changed.
                    speak_text("Cancelled.")
                    return

        run_actions(actions, frame=context.get("frame"))

    except FailSafe:
        raise
    except AppNotAllowed as exc:
        log.warning("Blocked app launch: %s", exc)
        speak_text("That app isn't on my allowed list, so I didn't open it.")
    except PlanError as exc:
        log.error("Invalid plan: %s", exc)
        speak_text("I couldn't turn that into a safe plan. Could you rephrase?")
    except BrainError as exc:
        log.error("Model error: %s", exc)
        speak_text("I couldn't reach the model. Check the connection and try again.")
    except Exception:
        log.exception("Unhandled error while handling a command")
        speak_text("Sorry, something went wrong.")


def _configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if cfg.LOG_FILE:
        handlers.append(logging.FileHandler(cfg.LOG_FILE, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def run() -> None:
    enable_dpi_awareness()
    _configure_logging()

    try:
        run_preflight(strict=True)
    except PreflightError as exc:
        print(exc, file=sys.stderr)
        print("Fix the items above and run again.", file=sys.stderr)
        raise SystemExit(1)

    log.info("%s", "=" * 60)
    log.info("  VoiceDesk")
    log.info("  Brain   : %s -> %s", cfg.LLM_BACKEND.upper(), cfg.active_model())
    log.info("  Speech  : %s", cfg.STT_BACKEND.upper())
    log.info("  Privacy : %s", "local only" if cfg.is_local_only() else "cloud")
    log.info(
        "  Safety  : confirmations %s, dry-run %s",
        "on" if cfg.CONFIRM_DANGEROUS else "OFF",
        "on" if cfg.DRY_RUN else "off",
    )
    log.info("%s", "=" * 60)
    log.info("  Listening. Say 'switch to gemini/groq/ollama' to change brain.")
    log.info("  Panic: slam the mouse into a screen corner to abort.")

    speak_text("VoiceDesk online.")

    try:
        listen_forever(handle_command)
    except KeyboardInterrupt:
        log.info("Interrupted. Shutting down.")
    except FailSafe:
        log.warning("Failsafe triggered. VoiceDesk stopped.")
    except MicError as exc:
        log.error("Microphone unavailable: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    run()
