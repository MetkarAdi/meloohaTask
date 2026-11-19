from types import SimpleNamespace

import pytest

from app.llm.groq import APIKey
from app.speech import transcription
from app.speech.router import _request_times


class FakeGroqClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        self.closed = False

    def create(self, **kwargs):
        assert kwargs["model"] == "whisper-large-v3-turbo"
        assert kwargs["file"][1].read() == b"audio-bytes"
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.result)

    def close(self):
        self.closed = True


class FakeGeminiClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, **kwargs):
        assert kwargs["contents"][0].inline_data.data == b"audio-bytes"
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.result)


def test_transcription_succeeds_with_groq_key_slot():
    client = FakeGroqClient("I asked about work")
    result = transcription.transcribe_audio(
        b"audio-bytes", filename="voice.webm", mime_type="audio/webm",
        keys=[APIKey("GROQ_API_KEY_2", "secret")], groq_client_factory=lambda _: client,
        gemini_api_key="",
    )
    assert (result.text, result.provider, result.key_slot) == ("I asked about work", "groq", "GROQ_API_KEY_2")
    assert client.closed


def test_groq_failure_falls_back_to_gemini():
    gemini = FakeGeminiClient("Namaste, meri career ke baare mein batao")
    result = transcription.transcribe_audio(
        b"audio-bytes", filename="voice.webm", mime_type="audio/webm",
        keys=[APIKey("GROQ_API_KEY", "secret")],
        groq_client_factory=lambda _: FakeGroqClient(error=RuntimeError("private error")),
        gemini_api_key="gemini-secret", gemini_client_factory=lambda _: gemini,
    )
    assert result.provider == "gemini"
    assert result.text.startswith("Namaste")


def test_empty_groq_answer_falls_back_to_gemini():
    result = transcription.transcribe_audio(
        b"audio-bytes", filename="voice.webm", mime_type="audio/webm",
        keys=[APIKey("GROQ_API_KEY", "secret")], groq_client_factory=lambda _: FakeGroqClient(" "),
        gemini_api_key="gemini-secret", gemini_client_factory=lambda _: FakeGeminiClient("from Gemini"),
    )
    assert (result.text, result.provider) == ("from Gemini", "gemini")


def test_groq_and_gemini_failure_is_friendly():
    with pytest.raises(transcription.TranscriptionUnavailable, match="couldn’t transcribe"):
        transcription.transcribe_audio(
            b"audio-bytes", filename="voice.webm", mime_type="audio/webm",
            keys=[APIKey("GROQ_API_KEY", "secret")],
            groq_client_factory=lambda _: FakeGroqClient(error=RuntimeError("secret provider detail")),
            gemini_api_key="gemini-secret",
            gemini_client_factory=lambda _: FakeGeminiClient(error=RuntimeError("secret provider detail")),
        )


def test_transcript_is_cleaned_and_capped_at_250_characters():
    from app.speech.router import clean_transcript

    text, truncated = clean_transcript("  hello\x00  there " + "x" * 300)
    assert len(text) == 250
    assert text.startswith("hello there")
    assert truncated is True
    assert clean_transcript("a  b") == ("a b", False)


def test_transcription_route_auth_validates_upload_and_never_writes_audio(client, monkeypatch, tmp_path):
    from app.speech import router as speech_router

    _request_times.clear()
    monkeypatch.setattr(speech_router, "transcribe_audio", lambda audio, **kwargs: transcription.TranscriptionResult("voice transcript", "groq", "GROQ_API_KEY"))
    unauthorized = client.post("/speech/transcribe", files={"file": ("voice.webm", b"audio", "audio/webm")}, data={"duration_seconds": "2"})
    assert unauthorized.status_code == 401

    signup = client.post("/auth/register", json={"email": "speech-route@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    response = client.post("/speech/transcribe", files={"file": ("voice.webm", b"audio", "audio/webm")}, data={"duration_seconds": "2"})
    assert response.status_code == 200, response.text
    assert response.json() == {"transcript": "voice transcript", "truncated": False}
    assert client.get("/wallet").json() == {"balance": 1}
    assert [path.name for path in tmp_path.iterdir()] == ["isolated-test.db"]

    oversized = client.post("/speech/transcribe", files={"file": ("voice.webm", b"x" * (10 * 1024 * 1024 + 1), "audio/webm")}, data={"duration_seconds": "2"})
    assert oversized.status_code == 413
    unsupported = client.post("/speech/transcribe", files={"file": ("voice.txt", b"not audio", "text/plain")}, data={"duration_seconds": "2"})
    assert unsupported.status_code == 415
    too_long = client.post("/speech/transcribe", files={"file": ("voice.webm", b"audio", "audio/webm")}, data={"duration_seconds": "30.1"})
    assert too_long.status_code == 422
