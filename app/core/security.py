"""Password hashing, JWT handling, login rate limiting."""

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed, RateLimited

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; we reject longer passwords instead of silently truncating.
    data = password.encode("utf-8")
    if len(data) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise ValueError("Password needs upper case, lower case and a digit")


def create_access_token(settings: Settings, user_id: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "iss": "sla",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], issuer="sla", options={"require": ["exp", "sub", "iss"]})
    except jwt.PyJWTError as exc:
        raise AuthenticationFailed("Invalid or expired token") from exc


class LoginRateLimiter:
    """Sliding-window limiter keyed by (ip, email). In-memory => per-process only (documented limitation)."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def check(self, key: str) -> None:
        with self._lock:
            q = self._prune(key, time.monotonic())
            if len(q) >= self.max_attempts:
                raise RateLimited("Too many failed login attempts. Try again later.")

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
