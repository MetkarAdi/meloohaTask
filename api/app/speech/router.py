from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.db.auth import get_current_user
from app.db.models import User
from .transcription import TranscriptionUnavailable, transcribe_audio

router = APIRouter(prefix="/speech", tags=["speech"])
LOGGER = logging.getLogger("melooha.speech.route")
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 30.0
MAX_REQUESTS_PER_MINUTE = 4
SUPPORTED_MIME_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}
_request_times: dict[int, deque[float]] = defaultdict(deque)
_rate_lock = threading.Lock()


class TranscriptionResponse(BaseModel):
    transcript: str
    truncated: bool


def clean_transcript(text: str, limit: int = 250) -> tuple[str, bool]:
    cleaned = " ".join(str(text).replace("\x00", "").split())
    return cleaned[:limit], len(cleaned) > limit


def _consume_rate_limit(user_id: int, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    with _rate_lock:
        recent = _request_times[user_id]
        while recent and current - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= MAX_REQUESTS_PER_MINUTE:
            return False
        recent.append(current)
        return True


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    file: UploadFile = File(...),
    duration_seconds: float = Form(..., gt=0),
    user: User = Depends(get_current_user),
):
    if duration_seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(status_code=422, detail="Recordings must be 30 seconds or shorter.")
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = SUPPORTED_MIME_TYPES.get(mime_type)
    if extension is None:
        await file.close()
        raise HTTPException(status_code=415, detail="This audio format isn’t supported. Please record in a supported browser format.")
    if not _consume_rate_limit(user.id):
        await file.close()
        raise HTTPException(status_code=429, detail="You’ve tried voice transcription a few times. Please wait a minute and try again.")

    try:
        audio = await file.read(MAX_AUDIO_BYTES + 1)
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio files must be 10 MB or smaller.")
        if not audio:
            raise HTTPException(status_code=422, detail="The recording was empty. Please record again.")
        result = transcribe_audio(
            audio,
            filename=file.filename or f"recording{extension}",
            mime_type=mime_type,
        )
        transcript, truncated = clean_transcript(result.text)
        LOGGER.info("Speech transcription delivered user_id=%s provider=%s truncated=%s", user.id, result.provider, truncated)
        return TranscriptionResponse(transcript=transcript, truncated=truncated)
    except HTTPException:
        raise
    except TranscriptionUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except Exception as error:
        LOGGER.warning("Speech route failed user_id=%s error=%s", user.id, type(error).__name__)
        raise HTTPException(status_code=503, detail="I couldn’t transcribe that clip. Please try recording again.") from None
    finally:
        await file.close()
