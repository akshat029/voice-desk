"""Microphone capture, voice activity detection, and transcription.

The input device now has exactly one owner. ``listen_once`` previously
opened a second ``sd.InputStream`` while ``listen_forever`` still held one
open, which double-captures audio and outright fails on drivers that want
exclusive access. Since confirmations run inside the main loop, that path
was hit by every dangerous action.
"""

from __future__ import annotations

import io
import logging
import queue
import time
import wave
from typing import Callable

import httpx
import numpy as np
import sounddevice as sd

import voicedesk.config as cfg

log = logging.getLogger(__name__)

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

BLOCK_SECONDS = 0.1


class MicError(RuntimeError):
    pass


# -- single-owner input stream ------------------------------------------


class _Microphone:
    def __init__(self) -> None:
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info
            if status:
                log.debug("Audio status: %s", status)
            self._queue.put(indata.copy().reshape(-1))

        try:
            self._stream = sd.InputStream(
                samplerate=cfg.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=int(cfg.SAMPLE_RATE * BLOCK_SECONDS),
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            raise MicError(f"could not open the microphone: {exc}") from exc

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    def get(self, timeout: float) -> np.ndarray:
        return self._queue.get(timeout=timeout)

    def drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


_mic = _Microphone()


# -- transcription ------------------------------------------------------

_whisper = None


def _local_model():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        log.info("Loading faster-whisper %s ...", cfg.WHISPER_MODEL)
        _whisper = WhisperModel(cfg.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def _to_wav(audio: np.ndarray) -> bytes:
    pcm = np.clip(audio, -1.0, 1.0)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(cfg.SAMPLE_RATE)
        handle.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return buffer.getvalue()


def _transcribe_local(audio: np.ndarray) -> str:
    segments, _ = _local_model().transcribe(audio, language="en", beam_size=1)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _transcribe_groq(audio: np.ndarray) -> str:
    # The old version skipped this check, so a missing key produced a 401
    # that the caller's bare except turned into silence forever.
    if not cfg.GROQ_API_KEY:
        raise MicError("STT_BACKEND=groq but GROQ_API_KEY is not set")

    resp = httpx.post(
        GROQ_STT_URL,
        headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
        files={"file": ("audio.wav", _to_wav(audio), "audio/wav")},
        data={"model": cfg.STT_MODEL, "language": "en"},
        timeout=cfg.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return str(resp.json().get("text", "")).strip()


def transcribe(audio: np.ndarray) -> str:
    if cfg.STT_BACKEND == "groq":
        return _transcribe_groq(audio)
    return _transcribe_local(audio)


# -- voice activity detection -------------------------------------------


def _collect_utterance(deadline: float | None) -> np.ndarray | None:
    """Collect one utterance using a simple RMS energy gate.

    This is still naive; see the Silero VAD issue for the real fix. It is
    at least shared by both entry points now, instead of duplicated.
    """
    speaking = False
    started_at = 0.0
    last_voice = 0.0
    recorded: list[np.ndarray] = []

    while deadline is None or time.monotonic() < deadline:
        try:
            chunk = _mic.get(timeout=0.2)
        except queue.Empty:
            continue

        now = time.monotonic()
        level = float(np.sqrt(np.mean(np.square(chunk))))

        if level >= cfg.ENERGY_THRESHOLD:
            if not speaking:
                speaking, started_at, recorded = True, now, []
            last_voice = now

        if not speaking:
            continue

        recorded.append(chunk)
        if (now - last_voice) * 1000 < cfg.SILENCE_MS:
            continue

        duration_ms = (now - started_at) * 1000
        audio = np.concatenate(recorded) if recorded else None
        speaking, recorded = False, []
        if audio is None or duration_ms < cfg.MIN_SPEECH_MS:
            continue
        return audio

    return None


def listen_once(timeout_seconds: float = 6.0) -> str:
    """Capture and transcribe a single short reply, for confirmations."""
    _mic.start()
    _mic.drain()
    audio = _collect_utterance(time.monotonic() + timeout_seconds)
    if audio is None:
        return ""
    try:
        return transcribe(audio)
    except Exception as exc:
        log.error("Transcription failed: %s", exc)
        return ""


def listen_forever(on_command: Callable[[str], None]) -> None:
    """Main loop: capture, transcribe, and hand the text to the callback."""
    _mic.start()
    try:
        while True:
            audio = _collect_utterance(None)
            if audio is None:
                continue
            try:
                text = transcribe(audio)
            except MicError as exc:
                # Configuration errors are fatal; failing silently here is
                # what made a missing API key look like a broken microphone.
                raise
            except Exception as exc:
                log.error("Transcription failed: %s", exc)
                continue

            if not text:
                continue

            on_command(text)
            # Drop anything captured while we were speaking or acting, so
            # the assistant does not hear itself.
            _mic.drain()
    finally:
        _mic.stop()
