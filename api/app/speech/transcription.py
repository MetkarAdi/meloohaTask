from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, Mapping, Sequence

from app.llm.groq import APIKey, configured_keys

LOGGER = logging.getLogger("melooha.speech")
WHISPER_MODEL = "whisper-large-v3-turbo"
GEMINI_TRANSCRIBE_MODEL = "gemini-3.5-flash-lite"
TRANSCRIPTION_FAILURE = "I couldn’t transcribe that clip. Please try recording again."


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    key_slot: str | None


class TranscriptionUnavailable(Exception):
    """Raised when every configured transcription provider fails."""


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("text") or "").strip()
    return str(getattr(value, "text", "") or "").strip()


def _groq_client(api_key: str):
    from groq import Groq

    return Groq(api_key=api_key, timeout=20.0, max_retries=0)


def _gemini_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key, http_options={"timeout": 20_000})


def transcribe_audio(
    audio: bytes,
    *,
    filename: str,
    mime_type: str,
    keys: Sequence[APIKey] | None = None,
    gemini_api_key: str | None = None,
    groq_client_factory: Callable[[str], Any] | None = None,
    gemini_client_factory: Callable[[str], Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> TranscriptionResult:
    """Try each Groq slot and then Gemini; all input bytes remain in memory."""
    env = os.environ if environ is None else environ
    groq_keys = list(keys) if keys is not None else configured_keys(env)
    groq_factory = groq_client_factory or _groq_client
    for key in groq_keys:
        client = None
        try:
            client = groq_factory(key.secret)
            response = client.audio.transcriptions.create(
                file=(filename, BytesIO(audio)),
                model=WHISPER_MODEL,
                response_format="json",
                temperature=0.0,
            )
            text = _text(response)
            if text:
                LOGGER.info("Speech transcription succeeded provider=groq key_slot=%s model=%s", key.slot, WHISPER_MODEL)
                return TranscriptionResult(text, "groq", key.slot)
            LOGGER.warning("Speech transcription returned empty text provider=groq key_slot=%s", key.slot)
        except Exception as error:
            LOGGER.warning("Speech transcription failed provider=groq key_slot=%s error=%s", key.slot, type(error).__name__)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    LOGGER.debug("Speech client cleanup failed provider=groq key_slot=%s", key.slot)

    selected_gemini_key = (gemini_api_key if gemini_api_key is not None else env.get("GEMINI_API_KEY", "")).strip()
    if selected_gemini_key:
        client = None
        try:
            client = (gemini_client_factory or _gemini_client)(selected_gemini_key)
            from google.genai import types

            response = client.models.generate_content(
                model=env.get("GEMINI_TRANSCRIPTION_MODEL", env.get("GEMINI_MODEL", GEMINI_TRANSCRIBE_MODEL)),
                contents=[
                    types.Part.from_bytes(data=audio, mime_type=mime_type),
                    "Transcribe the spoken words exactly in the language spoken. Return only the transcript, with no commentary.",
                ],
            )
            text = _text(response)
            if text:
                LOGGER.info("Speech transcription succeeded provider=gemini model=%s", env.get("GEMINI_TRANSCRIPTION_MODEL", env.get("GEMINI_MODEL", GEMINI_TRANSCRIBE_MODEL)))
                return TranscriptionResult(text, "gemini", None)
            LOGGER.warning("Speech transcription returned empty text provider=gemini")
        except Exception as error:
            LOGGER.warning("Speech transcription failed provider=gemini error=%s", type(error).__name__)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    LOGGER.debug("Speech client cleanup failed provider=gemini")

    raise TranscriptionUnavailable(TRANSCRIPTION_FAILURE)
