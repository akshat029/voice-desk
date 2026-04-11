import io
import logging
import queue
import time
import wave
from typing import Callable

import httpx
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from voicedesk.config import (
    ENERGY_THRESHOLD,
    GROQ_API_KEY,
    MIN_SPEECH_MS,
    SAMPLE_RATE,
    SILENCE_MS,
    STT_BACKEND,
    STT_MODEL,
    WHISPER_MODEL,
)

# ── Shared Whisper Model (singleton, only loaded if needed) ──

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def _audio_queue() -> tuple[queue.Queue, sd.InputStream]:
    chunks: queue.Queue = queue.Queue()

    def callback(indata, frames, time_info, status):
        del frames, time_info, status
        chunks.put(indata.copy().reshape(-1))

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=callback,
        blocksize=int(SAMPLE_RATE * 0.1),
    )
    return chunks, stream


def _drain(chunks: queue.Queue) -> None:
    while not chunks.empty():
        try:
            chunks.get_nowait()
        except queue.Empty:
            break


# ── Transcription Backends ───────────────────────────────────


def _transcribe_local(audio: np.ndarray) -> str:
    """Transcribe using local faster-whisper model."""
    model = _get_model()
    segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text


def _transcribe_groq(audio: np.ndarray) -> str:
    """Transcribe using Groq's cloud Whisper API (highest accuracy)."""
    # Convert numpy float32 [-1,1] to 16-bit WAV bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        int_data = (audio * 32767).astype(np.int16)
        wf.writeframes(int_data.tobytes())
    buf.seek(0)

    resp = httpx.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("audio.wav", buf, "audio/wav")},
        data={
            "model": STT_MODEL,
            "language": "en",
            "response_format": "text",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text.strip()


def _transcribe(audio: np.ndarray) -> str:
    """Route to the configured STT backend."""
    if STT_BACKEND == "groq":
        return _transcribe_groq(audio)
    return _transcribe_local(audio)


# ── One-Shot Listen (for confirmations) ─────────────────────


def listen_once(timeout_seconds: float = 5.0) -> str:
    """Record a single utterance and return the transcribed text."""
    chunks_q, stream = _audio_queue()
    speaking = False
    last_voice = 0.0
    recorded: list[np.ndarray] = []
    started_at = 0.0
    deadline = time.time() + timeout_seconds

    with stream:
        while time.time() < deadline:
            try:
                chunk = chunks_q.get(timeout=0.2)
            except queue.Empty:
                continue
            now = time.time()
            level = float(np.sqrt(np.mean(np.square(chunk))))
            if level >= ENERGY_THRESHOLD:
                if not speaking:
                    speaking = True
                    started_at = now
                    recorded = []
                last_voice = now
            if speaking:
                recorded.append(chunk)
            if speaking and (now - last_voice) * 1000 >= SILENCE_MS:
                speaking = False
                duration_ms = (now - started_at) * 1000
                audio = np.concatenate(recorded) if recorded else np.array([], dtype=np.float32)
                recorded = []
                if duration_ms < MIN_SPEECH_MS or not len(audio):
                    continue
                return _transcribe(audio)
    return ""


# ── Continuous Listen Loop ───────────────────────────────────


def listen_forever(on_command: Callable[[str], None]) -> None:
    # Pre-load local model only if using local STT
    if STT_BACKEND == "local":
        _get_model()
        logging.info("Local Whisper model loaded.")
    else:
        logging.info(f"Using Groq cloud STT ({STT_MODEL})")

    chunks, stream = _audio_queue()
    speaking = False
    last_voice = 0.0
    recorded: list[np.ndarray] = []
    started_at = 0.0
    with stream:
        while True:
            chunk = chunks.get()
            now = time.time()
            level = float(np.sqrt(np.mean(np.square(chunk))))
            if level >= ENERGY_THRESHOLD:
                if not speaking:
                    speaking = True
                    started_at = now
                    recorded = []
                last_voice = now
            if speaking:
                recorded.append(chunk)
            if speaking and (now - last_voice) * 1000 >= SILENCE_MS:
                speaking = False
                duration_ms = (now - started_at) * 1000
                audio = np.concatenate(recorded) if recorded else np.array([], dtype=np.float32)
                recorded = []
                if duration_ms < MIN_SPEECH_MS or not len(audio):
                    continue
                try:
                    command = _transcribe(audio)
                except Exception as exc:
                    logging.error(f"STT failed: {exc}")
                    continue
                if command:
                    on_command(command)
                _drain(chunks)
