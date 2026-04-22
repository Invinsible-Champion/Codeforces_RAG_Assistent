"""
Authentication helpers — password hashing (bcrypt) and signed-cookie sessions.
"""

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response

from config import SECRET_KEY, SESSION_MAX_AGE


# ── Password hashing ─────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    pwd_bytes = plain.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check *plain* against a bcrypt *hashed* value."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Signed-cookie sessions ───────────────────────────────────────────
_serializer = URLSafeTimedSerializer(SECRET_KEY)
_COOKIE_NAME = "cf_session"


def create_session(response: Response, user_id: int, cf_handle: str) -> None:
    """Set a signed session cookie on *response*."""
    token = _serializer.dumps({"uid": user_id, "handle": cf_handle})
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def get_current_user(request: Request) -> dict | None:
    """
    Return ``{"uid": …, "handle": …}`` if the request carries a valid
    session cookie, or *None* otherwise.
    """
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def clear_session(response: Response) -> None:
    """Delete the session cookie."""
    response.delete_cookie(_COOKIE_NAME, path="/")
