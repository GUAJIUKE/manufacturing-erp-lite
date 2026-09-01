"""Security primitives: bcrypt password hashing and JWT tokens.

Uses passlib[bcrypt] for password hashing (pure-Python bcrypt, no native
build issues on Windows) and python-jose for HS256 tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import UnauthorizedException

#: Passlib context; bcrypt has a 72-byte password limit, enforced upstream.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(
    subject: str,
    *,
    expires_minutes: int | None = None,
    extra: dict | None = None,
) -> str:
    """Create an HS256 JWT.

    ``subject`` is the username (stable, never changes). Non-identifying
    claims (user id, role code) ride in ``extra`` so the token stays small.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict = {"sub": subject, "iat": now, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a token; raise UnauthorizedException on failure."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedException("登录已过期，请重新登录") from exc
