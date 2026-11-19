from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Cookie, HTTPException, Response
from sqlalchemy import select

from .models import User
from .session import get_session_factory

COOKIE_NAME = "melooha_session"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 14


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Set JWT_SECRET to at least 32 characters to enable login.")
    return secret.encode("utf-8")


def ensure_auth_configured() -> None:
    _secret()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_value, digest_value = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected = _b64decode(digest_value)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=_b64decode(salt_value), n=2**14, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps({"sub": str(user_id), "exp": int(time.time()) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64encode(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> int:
    try:
        header_value, payload_value, signature = token.split(".")
        header = json.loads(_b64decode(header_value))
        payload = json.loads(_b64decode(payload_value))
        signing_input = f"{header_value}.{payload_value}".encode("ascii")
        expected = _b64encode(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
        if header.get("alg") != "HS256" or not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired token")
        user_id = int(payload["sub"])
        if user_id < 1:
            raise ValueError("invalid user")
        return user_id
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Session expired or invalid; please sign in again.") from exc


def set_session_cookie(response: Response, user_id: int) -> None:
    secure = os.getenv("COOKIE_SECURE", "").lower() == "true" or os.getenv("APP_ENV", "").lower() in {"prod", "production"}
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_access_token(user_id),
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, httponly=True, samesite="lax", path="/")


def get_current_user(
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    user_id = decode_access_token(token)
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        session.expunge(user)
    return user
