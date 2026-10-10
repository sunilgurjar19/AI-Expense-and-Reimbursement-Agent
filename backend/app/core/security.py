from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Raised when a token is missing, expired or invalid."""


def create_access_token(user_id: str) -> str:
    settings = get_settings().auth
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Return the user id encoded in the token."""
    settings = get_settings().auth
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token has no subject")
    return user_id
