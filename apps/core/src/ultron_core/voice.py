"""Speech-to-text in ULTRON Core (faster-whisper, runs on this PC).

The Windows app records a short WAV clip and sends it here; the text comes
back. Nothing is stored and the words are not logged. Because it runs on
the user's own machine, private conversations may use it too.

The model loads on first use (or via /voice/warmup) and stays in memory;
one clip is transcribed at a time to keep CPU and RAM use predictable.
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
import wave
from typing import Any, Protocol

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from ultron_core import ratelimit
from ultron_core.config import Settings
from ultron_core.deps import PrincipalDep, RedisDep, SettingsDep
from ultron_core.logging_setup import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class VoiceError(Exception):
    def __init__(self, message: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def decode_wav(data: bytes) -> np.ndarray:
    """PCM WAV (8/16/32-bit, any rate, mono or stereo) -> 16 kHz mono float32."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise VoiceError("The recording isn't a WAV file ULTRON can read.") from exc
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise VoiceError("Unsupported WAV sample size.")
    if channels > 1:
        audio = audio[: len(audio) - len(audio) % channels].reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = round(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return audio.astype(np.float32)


def language_code(value: str | None) -> str | None:
    """'hi-IN' -> 'hi', 'en_US' -> 'en', 'auto'/'' -> None (detect)."""
    if not value or value.lower() == "auto":
        return None
    code = value.replace("_", "-").split("-")[0].lower()
    return code if code.isalpha() and 2 <= len(code) <= 3 else None


class Transcriber(Protocol):
    model_name: str

    @property
    def loaded(self) -> bool: ...

    def load(self) -> None: ...

    def transcribe(self, audio: np.ndarray, language: str | None) -> tuple[str, str]: ...


class WhisperTranscriber:
    """faster-whisper on the CPU (int8). Thread-safe lazy loading."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.stt_model
        self._settings = settings
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel  # heavy import, only when used

            started = time.perf_counter()
            self._model = WhisperModel(
                self.model_name,
                device=self._settings.stt_device,
                compute_type=self._settings.stt_compute_type,
                download_root=self._settings.stt_model_dir,
                cpu_threads=self._settings.stt_cpu_threads,
            )
            log.info(
                "voice.model_loaded",
                model=self.model_name,
                seconds=round(time.perf_counter() - started, 1),
            )

    def transcribe(self, audio: np.ndarray, language: str | None) -> tuple[str, str]:
        self.load()
        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=True,  # skip silence before/after speech
            condition_on_previous_text=False,  # avoids repetition loops
            temperature=0.0,
            without_timestamps=True,
            max_new_tokens=200,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


# --- API --------------------------------------------------------------------------

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceStatus(BaseModel):
    available: bool
    model: str
    loaded: bool
    device: str


class TranscriptOut(BaseModel):
    text: str
    language: str
    audio_seconds: float
    seconds: float
    model: str


def _transcriber(request: Request) -> Transcriber:
    t = getattr(request.app.state, "transcriber", None)
    if t is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Speech-to-text is turned off."
        )
    return t


@router.get("/status", response_model=VoiceStatus)
async def voice_status(
    request: Request, principal: PrincipalDep, settings: SettingsDep
) -> VoiceStatus:
    t = getattr(request.app.state, "transcriber", None)
    return VoiceStatus(
        available=t is not None,
        model=settings.stt_model,
        loaded=bool(t and t.loaded),
        device=settings.stt_device,
    )


@router.post("/warmup", response_model=VoiceStatus)
async def voice_warmup(
    request: Request, principal: PrincipalDep, settings: SettingsDep
) -> VoiceStatus:
    """Loads the speech model now so the first command isn't slow."""
    t = _transcriber(request)
    try:
        await asyncio.to_thread(t.load)
    except Exception as exc:  # download/network/model problems
        log.warning("voice.model_load_failed", error=type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The speech model couldn't be loaded ({type(exc).__name__}). "
            "The first time, ULTRON Core needs internet to download it.",
        ) from None
    return VoiceStatus(
        available=True, model=settings.stt_model, loaded=t.loaded, device=settings.stt_device
    )


@router.post("/transcribe", response_model=TranscriptOut)
async def transcribe(
    request: Request,
    principal: PrincipalDep,
    settings: SettingsDep,
    redis: RedisDep,
    audio: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=12),
) -> TranscriptOut:
    t = _transcriber(request)
    if not await ratelimit.allow(
        redis, settings, bucket="stt", identity=str(principal.user.id), limit=30, window=60
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many voice requests; wait a moment."
        )
    data = await audio.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="The recording is too long.")
    try:
        samples = decode_wav(data)
    except VoiceError as exc:
        raise HTTPException(exc.code, detail=exc.message) from None
    duration = len(samples) / SAMPLE_RATE
    if duration > settings.stt_max_seconds:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Recordings can be up to {settings.stt_max_seconds} seconds.",
        )
    if duration < 0.2 or float(np.abs(samples).max(initial=0.0)) < 1e-3:
        return TranscriptOut(
            text="", language="", audio_seconds=round(duration, 2), seconds=0.0, model=t.model_name
        )
    lock: asyncio.Lock = request.app.state.transcribe_lock
    started = time.perf_counter()
    try:
        async with lock, asyncio.timeout(settings.stt_timeout_seconds):
            text, lang = await asyncio.to_thread(t.transcribe, samples, language_code(language))
    except TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, detail="Transcription took too long."
        ) from None
    except Exception as exc:
        log.warning("voice.transcribe_failed", error=type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech-to-text failed ({type(exc).__name__}).",
        ) from None
    seconds = round(time.perf_counter() - started, 2)
    # Timing only: the words themselves are never logged.
    log.info("voice.transcribed", audio_seconds=round(duration, 2), seconds=seconds, language=lang)
    return TranscriptOut(
        text=text,
        language=lang,
        audio_seconds=round(duration, 2),
        seconds=seconds,
        model=t.model_name,
    )
