"""Speech-to-text in Core: WAV decoding, the transcribe API (with a fake
model) and, when the model is available locally, real faster-whisper."""

from __future__ import annotations

import io
import math
import os
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import owner_headers
from tests.fakes import cloud
from ultron_core import voice


def wav_bytes(
    seconds: float = 1.0,
    rate: int = 22050,
    channels: int = 1,
    freq: float = 440.0,
    amp: float = 0.3,
) -> bytes:
    n = int(seconds * rate)
    frames = b"".join(
        struct.pack(
            "<" + "h" * channels,
            *([int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))] * channels),
        )
        for i in range(n)
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def test_decode_wav_resamples_to_16k_mono() -> None:
    audio = voice.decode_wav(wav_bytes(1.0, rate=22050, channels=2))
    assert audio.dtype == np.float32
    assert abs(len(audio) - 16000) <= 1
    assert 0.25 < float(np.abs(audio).max()) < 0.35
    with pytest.raises(voice.VoiceError):
        voice.decode_wav(b"not a wav file")


def test_language_codes() -> None:
    assert voice.language_code("hi-IN") == "hi"
    assert voice.language_code("en_US") == "en"
    assert voice.language_code("auto") is None
    assert voice.language_code(None) is None
    assert voice.language_code("12") is None


class FakeTranscriber:
    model_name = "fake-small"

    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None]] = []
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def transcribe(self, audio: np.ndarray, language: str | None) -> tuple[str, str]:
        self.load()
        self.calls.append((len(audio), language))
        return ("मुझे नौ बजे याद दिलाना" if language == "hi" else "open notepad"), language or "en"


@pytest.mark.integration
async def test_transcribe_api(migrated_database) -> None:  # type: ignore[no-untyped-def]
    import httpx
    from asgi_lifespan import LifespanManager

    from tests.conftest import _reset_state
    from ultron_core.main import create_app

    fake = FakeTranscriber()
    app = create_app(migrated_database, ai_providers=[cloud()], transcriber=fake)
    async with LifespanManager(app):
        await _reset_state(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://u.test"
        ) as c:
            anon = await c.post(
                "/api/v1/voice/transcribe", files={"audio": ("a.wav", wav_bytes(), "audio/wav")}
            )
            assert anon.status_code == 401
            h = await owner_headers(app, c)
            st = (await c.get("/api/v1/voice/status", headers=h)).json()
            assert st == {"available": True, "model": "small", "loaded": False, "device": "cpu"}
            assert (await c.post("/api/v1/voice/warmup", headers=h)).json()["loaded"] is True

            ok = await c.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("a.wav", wav_bytes(1.0), "audio/wav")},
                data={"language": "en-IN"},
                headers=h,
            )
            assert ok.status_code == 200, ok.text
            body = ok.json()
            assert body["text"] == "open notepad" and body["model"] == "fake-small"
            assert abs(body["audio_seconds"] - 1.0) < 0.01 and body["seconds"] >= 0
            assert fake.calls[-1] == (16000, "en")
            hi = await c.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
                data={"language": "hi-IN"},
                headers=h,
            )
            assert hi.json()["text"].startswith("मुझे")

            # Silence: no model call, empty text.
            calls = len(fake.calls)
            quiet = await c.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("a.wav", wav_bytes(amp=0.0), "audio/wav")},
                headers=h,
            )
            assert quiet.json()["text"] == "" and len(fake.calls) == calls
            bad = await c.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("a.wav", b"garbage", "audio/wav")},
                headers=h,
            )
            assert bad.status_code == 422
            long = await c.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("a.wav", wav_bytes(61.0, rate=8000), "audio/wav")},
                headers=h,
            )
            assert long.status_code == 413
        await _reset_state(app)


@pytest.mark.integration
async def test_voice_off(migrated_database) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import running_app

    settings = migrated_database.model_copy(update={"stt_enabled": False})
    async with running_app(settings, [cloud()]) as (app, c):
        h = await owner_headers(app, c)
        assert (await c.get("/api/v1/voice/status", headers=h)).json()["available"] is False
        r = await c.post(
            "/api/v1/voice/transcribe",
            files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
            headers=h,
        )
        assert r.status_code == 503


MODEL_DIR = os.environ.get("ULTRON_TEST_WHISPER_DIR")
SAMPLE = os.environ.get("ULTRON_TEST_WHISPER_WAV")


@pytest.mark.skipif(
    not (MODEL_DIR and SAMPLE), reason="set ULTRON_TEST_WHISPER_DIR and ULTRON_TEST_WHISPER_WAV"
)
def test_real_whisper_transcribes_english() -> None:
    from ultron_core.config import Settings

    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        jwt_secret="j" * 40,
        local_database_url="postgresql://u:p@db/x",
        stt_model="small",
        stt_model_dir=MODEL_DIR,
    )
    t = voice.WhisperTranscriber(s)
    text, lang = t.transcribe(voice.decode_wav(Path(SAMPLE).read_bytes()), "en")  # type: ignore[arg-type]
    assert lang == "en"
    assert "notepad" in text.lower()
