import logging
import time

import voicedesk.config as cfg
from voicedesk.brain import plan_actions
from voicedesk.executor import run_actions, speak_text
from voicedesk.listener import listen_forever, listen_once
from voicedesk.vision import get_context

# Keys/actions considered dangerous and requiring confirmation
_DANGEROUS_HOTKEYS = {"delete", "backspace", "f4"}
_DANGEROUS_ACTIONS = {"drag"}


def _describe_action(action: dict) -> str:
    """Return a human-readable description of an action."""
    kind = action.get("action", "")
    if kind == "hotkey":
        keys = action.get("keys", [])
        return f"press {' + '.join(str(k) for k in keys)}"
    if kind == "press":
        keys = action.get("keys") or [action.get("text", "")]
        return f"press {', '.join(str(k) for k in keys)}"
    if kind == "type":
        text = str(action.get("text", ""))[:40]
        return f"type '{text}'"
    if kind == "drag":
        return f"drag to ({action.get('x')}, {action.get('y')})"
    if kind == "open_app":
        return f"open {action.get('name', 'app')}"
    return kind


def _is_dangerous(action: dict) -> bool:
    """Check if an action is potentially destructive."""
    kind = action.get("action", "")
    if kind in _DANGEROUS_ACTIONS:
        return True
    if kind == "hotkey":
        keys = {str(k).lower() for k in action.get("keys", [])}
        if keys & _DANGEROUS_HOTKEYS:
            return True
        if "alt" in keys and "f4" in keys:
            return True
        if "ctrl" in keys and ("w" in keys or "q" in keys):
            return True
    if kind == "press":
        keys_list = action.get("keys") or [action.get("text", "")]
        if any(str(k).lower() in _DANGEROUS_HOTKEYS for k in keys_list):
            return True
    return False


def _confirm_action(action: dict) -> bool:
    """Ask user for voice confirmation before a dangerous action."""
    desc = _describe_action(action)
    speak_text(f"I'm about to {desc}. Should I proceed?")
    logging.info(f"Safety: awaiting confirmation for '{desc}'")
    response = listen_once(timeout_seconds=5.0)
    logging.info(f"Safety: user said '{response}'")
    affirmative = {"yes", "yeah", "yep", "sure", "go ahead", "do it", "proceed", "okay", "ok"}
    return any(word in response.lower() for word in affirmative)


def _check_backend_switch(command_text: str) -> bool:
    """Handle voice commands to switch LLM backends. Returns True if handled."""
    lowered = command_text.lower()
    if "switch to gemini" in lowered or "use gemini" in lowered:
        cfg.LLM_BACKEND = "gemini"
        speak_text("Switched to Google Gemini.")
        logging.info("Backend switched to GEMINI")
        return True
    if "switch to groq" in lowered or "use groq" in lowered:
        cfg.LLM_BACKEND = "groq"
        speak_text("Switched to Groq.")
        logging.info("Backend switched to GROQ")
        return True
    if "switch to ollama" in lowered or "use ollama" in lowered:
        cfg.LLM_BACKEND = "ollama"
        speak_text("Switched to Ollama.")
        logging.info("Backend switched to OLLAMA")
        return True
    return False


def _handle_command(command_text: str) -> None:
    logging.info(f"Heard: \"{command_text}\"")

    # Check for backend switch voice commands
    if _check_backend_switch(command_text):
        return

    t0 = time.perf_counter()
    try:
        context = get_context(command_text)
        actions = plan_actions(command_text, context)
        if not actions:
            raise ValueError("No actions returned by LLM")
        elapsed = time.perf_counter() - t0
        logging.info(f"Planned {len(actions)} action(s) in {elapsed:.1f}s")

        # Safety confirmation for dangerous actions
        if cfg.CONFIRM_DANGEROUS:
            safe_actions = []
            for action in actions:
                if _is_dangerous(action):
                    if _confirm_action(action):
                        safe_actions.append(action)
                    else:
                        speak_text("Cancelled.")
                        logging.info(f"Safety: user cancelled '{_describe_action(action)}'")
                else:
                    safe_actions.append(action)
            actions = safe_actions

        if actions:
            run_actions(actions)

    except Exception as exc:
        message = f"Error: {exc}"
        logging.error(message)
        if cfg.TTS_ENABLED:
            speak_text(f"Sorry, something went wrong. {exc}")


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("voicedesk.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    model_name = cfg.OLLAMA_MODEL if cfg.LLM_BACKEND == "ollama" else (
        cfg.GEMINI_MODEL if cfg.LLM_BACKEND == "gemini" else cfg.GROQ_MODEL
    )
    privacy = "LOCAL (private)" if cfg.LLM_BACKEND == "ollama" else "CLOUD"

    logging.info("=" * 50)
    logging.info("      VoiceDesk v2.0 - Desktop Assistant")
    logging.info("=" * 50)
    logging.info(f"  Backend  : {cfg.LLM_BACKEND.upper()} -> {model_name}")
    logging.info(f"  Privacy  : {privacy}")
    logging.info(f"  Safety   : {'ON' if cfg.CONFIRM_DANGEROUS else 'OFF'}")
    logging.info("=" * 50)
    logging.info("  Listening... speak a command anytime.")
    logging.info("  Say 'switch to gemini/groq/ollama' to change backend.")

    if cfg.TTS_ENABLED:
        speak_text("VoiceDesk online. Awaiting your command.")
    listen_forever(_handle_command)
