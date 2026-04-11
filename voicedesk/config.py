import os

from dotenv import load_dotenv

load_dotenv()

# ── LLM Backend ─────────────────────────────────────────────
# "groq" = cloud, fast  |  "gemini" = cloud, vision  |  "ollama" = local
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")

# Ollama (local)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Groq (cloud — free tier)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Google Gemini (cloud — free tier, vision-capable)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Whether the configured model accepts image/vision input.
# "auto" → true for ollama & gemini, false for groq text models
VISION_LLM = os.getenv("VISION_LLM", "auto")

# ── Whisper STT ──────────────────────────────────────────────
# "local" = faster-whisper on CPU  |  "groq" = Groq cloud Whisper (best accuracy)
STT_BACKEND = os.getenv("STT_BACKEND", "groq")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))
ENERGY_THRESHOLD = float(os.getenv("ENERGY_THRESHOLD", "0.015"))
SILENCE_MS = int(os.getenv("SILENCE_MS", "700"))
MIN_SPEECH_MS = int(os.getenv("MIN_SPEECH_MS", "250"))

# ── Vision / Screen ─────────────────────────────────────────
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
MAX_OCR_CHARS = int(os.getenv("MAX_OCR_CHARS", "4000"))

# ── TTS ──────────────────────────────────────────────────────
TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() == "true"

# ── Safety ───────────────────────────────────────────────────
CONFIRM_DANGEROUS = os.getenv("CONFIRM_DANGEROUS", "true").lower() == "true"

# ── Network ──────────────────────────────────────────────────
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "60"))

# ── Conversation History ─────────────────────────────────────
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))


def supports_vision() -> bool:
    """Check if the active LLM backend supports image input."""
    v = VISION_LLM.lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return LLM_BACKEND in ("ollama", "gemini")
