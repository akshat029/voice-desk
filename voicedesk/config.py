"""Central configuration for VoiceDesk.

Every setting is read from the environment, optionally via a local ``.env``
file. This module has no side effects beyond ``load_dotenv()`` so it is safe
to import from anywhere, including :mod:`voicedesk.preflight`, which runs
before the rest of the app boots.

Defaults are deliberately *coherently local*: Ollama for reasoning and
faster-whisper for speech. Nothing leaves the machine until you explicitly
opt into a cloud backend. Previously the shipped defaults mixed a local LLM
with cloud speech-to-text, which quietly contradicted the privacy claims in
the README.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


# -- environment helpers -------------------------------------------------


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = _str(name, default)
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = _str(name, default).lower()
    return value if value in allowed else default


# -- LLM backend ---------------------------------------------------------
# "ollama" = local and private | "groq" = cloud and fast | "gemini" = vision

LLM_BACKENDS = {"ollama", "groq", "gemini"}
LLM_BACKEND = _choice("LLM_BACKEND", "ollama", LLM_BACKENDS)

# Ollama (local). The tag must be one you have actually pulled; check with
# `ollama list`. Preflight verifies this at startup instead of failing on
# the first command.
OLLAMA_MODEL = _str("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = _str("OLLAMA_URL", "http://localhost:11434/api/chat")

# Groq (cloud, free tier)
GROQ_API_KEY = _str("GROQ_API_KEY", "")
GROQ_MODEL = _str("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Google Gemini (cloud, free tier, vision-capable)
GEMINI_API_KEY = _str("GEMINI_API_KEY", "")
GEMINI_MODEL = _str("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = _str(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)

# Does the active model accept image input?
#   "auto"  -> Gemini only. The default Groq and Ollama models are text-only,
#              so "auto" no longer claims vision on their behalf and then
#              throws the screenshot away.
#   "true"  -> force on (set this when running llava, qwen2.5vl, etc.)
#   "false" -> force off
VISION_LLM = _choice("VISION_LLM", "auto", {"auto", "true", "false"})


# -- speech to text ------------------------------------------------------
# "local" = faster-whisper on CPU (private) | "groq" = Groq cloud Whisper

STT_BACKENDS = {"local", "groq"}
STT_BACKEND = _choice("STT_BACKEND", "local", STT_BACKENDS)
WHISPER_MODEL = _str("WHISPER_MODEL", "base")
STT_MODEL = _str("STT_MODEL", "whisper-large-v3-turbo")
SAMPLE_RATE = _int("SAMPLE_RATE", 16000)
ENERGY_THRESHOLD = _float("ENERGY_THRESHOLD", 0.015)
SILENCE_MS = _int("SILENCE_MS", 700)
MIN_SPEECH_MS = _int("MIN_SPEECH_MS", 250)


# -- vision and screen ---------------------------------------------------

OCR_ENABLED = _bool("OCR_ENABLED", True)
MAX_OCR_CHARS = _int("MAX_OCR_CHARS", 4000)

# Explicit path to the Tesseract binary. Leave blank to auto-discover.
TESSERACT_CMD = _str("TESSERACT_CMD", "")

# Which monitor to capture. 1 is the primary display. Index 0 is the
# stitched virtual desktop spanning every monitor, whose origin can be
# negative, so it is never a safe basis for coordinate math.
CAPTURE_MONITOR = _int("CAPTURE_MONITOR", 1)

# Long edge of the screenshot sent to the model. A full-resolution 4K PNG
# costs seconds of upload and thousands of tokens for no accuracy gain.
MAX_SCREENSHOT_DIM = _int("MAX_SCREENSHOT_DIM", 1280)


# -- text to speech ------------------------------------------------------

TTS_ENABLED = _bool("TTS_ENABLED", True)
TTS_RATE = _int("TTS_RATE", 175)
# Substring matched against installed voice names, e.g. "zira" or "samantha".
TTS_VOICE_HINT = _str("TTS_VOICE_HINT", "")


# -- safety --------------------------------------------------------------

CONFIRM_DANGEROUS = _bool("CONFIRM_DANGEROUS", True)
CONFIRM_TIMEOUT = _float("CONFIRM_TIMEOUT", 6.0)

# Log the plan and skip every side effect. Invaluable while iterating on
# prompts, and the safest way to try a new backend.
DRY_RUN = _bool("DRY_RUN", False)

# Only these app names may be launched. `open_app` used to hand an
# LLM-controlled string straight to a subprocess, which was an arbitrary
# code execution path reachable from any text visible on screen.
APP_ALLOWLIST = _csv(
    "APP_ALLOWLIST",
    "chrome,firefox,msedge,code,notepad,calc,explorer,spotify,slack,notion",
)

# Apps that earn a destructive-tier confirmation, because typing into them
# can execute commands. Not allowlisted by default.
SHELL_APPS = _csv(
    "SHELL_APPS", "cmd,powershell,pwsh,wt,terminal,iterm,bash,zsh"
)


# -- network -------------------------------------------------------------

REQUEST_TIMEOUT = _float("REQUEST_TIMEOUT", 120.0)
MAX_RETRIES = _int("MAX_RETRIES", 3)
RETRY_BASE_DELAY = _float("RETRY_BASE_DELAY", 0.75)


# -- conversation history ------------------------------------------------

MAX_HISTORY = _int("MAX_HISTORY", 10)


# -- logging -------------------------------------------------------------

LOG_FILE = _str("LOG_FILE", "voicedesk.log")
LOG_LEVEL = _str("LOG_LEVEL", "INFO").upper()

# Transcripts and model output are sensitive: the log used to record every
# word heard in plaintext. Opt in only while debugging.
LOG_TRANSCRIPTS = _bool("LOG_TRANSCRIPTS", False)


# -- derived helpers -----------------------------------------------------


def supports_vision() -> bool:
    """Whether the *currently active* backend accepts image input."""
    if VISION_LLM == "true":
        return True
    if VISION_LLM == "false":
        return False
    return LLM_BACKEND == "gemini"


def active_model() -> str:
    """Human-readable name of the model behind the active backend."""
    if LLM_BACKEND == "ollama":
        return OLLAMA_MODEL
    if LLM_BACKEND == "gemini":
        return GEMINI_MODEL
    return GROQ_MODEL


def is_local_only() -> bool:
    """True when no audio, text, or pixels leave this machine."""
    return LLM_BACKEND == "ollama" and STT_BACKEND == "local"
