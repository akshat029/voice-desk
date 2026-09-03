"""Startup checks, so VoiceDesk fails loudly instead of degrading silently.

Before this existed a fresh clone would announce "VoiceDesk online" and then
ignore every command forever: ``.env.example`` never mentioned
``STT_BACKEND``, so the shipped config fell through to Groq cloud speech
with an empty API key, and the default Ollama tag did not exist. Both
failures were swallowed by broad excepts.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

import voicedesk.config as cfg


@dataclass(frozen=True)
class Problem:
    fatal: bool
    what: str
    fix: str

    def render(self) -> str:
        marker = "FAIL" if self.fatal else "WARN"
        return f"  [{marker}] {self.what}\n         -> {self.fix}"


class PreflightError(RuntimeError):
    """Raised when a fatal misconfiguration would make VoiceDesk useless."""


def _ollama_base() -> str:
    parsed = urlparse(cfg.OLLAMA_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def check_python() -> list[Problem]:
    if sys.version_info < (3, 10):
        return [
            Problem(
                True,
                f"Python {sys.version.split()[0]} is too old.",
                "VoiceDesk needs Python 3.10 or newer.",
            )
        ]
    return []


def check_microphone() -> list[Problem]:
    try:
        import sounddevice as sd

        device = sd.query_devices(kind="input")
    except Exception as exc:
        return [
            Problem(
                True,
                f"No usable microphone: {exc}",
                "Connect an input device and check OS microphone permissions.",
            )
        ]
    if not device:
        return [
            Problem(
                True,
                "No default microphone found.",
                "Pick a default input device in your OS sound settings.",
            )
        ]
    return []


def check_llm() -> list[Problem]:
    """Validate the active LLM backend. Also called on voice backend switch."""
    backend = cfg.LLM_BACKEND

    if backend == "groq":
        if not cfg.GROQ_API_KEY:
            return [
                Problem(
                    True,
                    "LLM_BACKEND=groq but GROQ_API_KEY is empty.",
                    "Grab a free key at https://console.groq.com/keys and set it in .env",
                )
            ]
        return []

    if backend == "gemini":
        if not cfg.GEMINI_API_KEY:
            return [
                Problem(
                    True,
                    "LLM_BACKEND=gemini but GEMINI_API_KEY is empty.",
                    "Grab a free key at https://aistudio.google.com/apikey and set it in .env",
                )
            ]
        return []

    base = _ollama_base()
    try:
        resp = httpx.get(f"{base}/api/tags", timeout=5.0)
        resp.raise_for_status()
        tags = {str(m.get("name", "")) for m in resp.json().get("models", [])}
    except Exception as exc:
        return [
            Problem(
                True,
                f"Cannot reach Ollama at {base} ({exc}).",
                "Start it with `ollama serve`, or switch LLM_BACKEND in .env",
            )
        ]

    wanted = cfg.OLLAMA_MODEL
    if wanted not in tags and f"{wanted}:latest" not in tags:
        available = ", ".join(sorted(tags)[:8]) or "none"
        return [
            Problem(
                True,
                f"Ollama model {wanted!r} is not pulled. Available: {available}",
                f"Run `ollama pull {wanted}`, or set OLLAMA_MODEL to a tag you have.",
            )
        ]
    return []


def check_stt() -> list[Problem]:
    if cfg.STT_BACKEND == "groq":
        if not cfg.GROQ_API_KEY:
            return [
                Problem(
                    True,
                    "STT_BACKEND=groq but GROQ_API_KEY is empty.",
                    "Set GROQ_API_KEY, or use STT_BACKEND=local for offline speech.",
                )
            ]
        return []
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:
        return [
            Problem(
                True,
                f"faster-whisper is not importable ({exc}).",
                "pip install -r requirements.txt",
            )
        ]
    return []


def check_ocr() -> list[Problem]:
    if not cfg.OCR_ENABLED:
        return []
    from voicedesk.vision import find_tesseract

    if find_tesseract() is None:
        hint = (
            "https://github.com/UB-Mannheim/tesseract/wiki"
            if platform.system() == "Windows"
            else "your package manager"
        )
        return [
            Problem(
                False,
                "Tesseract OCR was not found, so screen text will be unavailable.",
                f"Install it from {hint}, set TESSERACT_CMD, or set OCR_ENABLED=false.",
            )
        ]
    return []


def check_vision_consistency() -> list[Problem]:
    if cfg.LLM_BACKEND == "groq" and cfg.VISION_LLM == "true":
        return [
            Problem(
                False,
                "VISION_LLM=true with a Groq text model burns a screenshot per command.",
                "Use LLM_BACKEND=gemini for vision, or set VISION_LLM=auto.",
            )
        ]
    return []


CHECKS = (
    check_python,
    check_microphone,
    check_llm,
    check_stt,
    check_ocr,
    check_vision_consistency,
)


def collect_problems() -> list[Problem]:
    problems: list[Problem] = []
    for check in CHECKS:
        problems.extend(check())
    return problems


def run_preflight(strict: bool = True) -> list[Problem]:
    """Report configuration problems. Raises on fatal ones when strict."""
    problems = collect_problems()
    if not problems:
        return problems

    report = "\n".join(
        ["", "Preflight found issues:"] + [p.render() for p in problems] + [""]
    )
    if strict and any(p.fatal for p in problems):
        raise PreflightError(report)
    print(report, file=sys.stderr)
    return problems
