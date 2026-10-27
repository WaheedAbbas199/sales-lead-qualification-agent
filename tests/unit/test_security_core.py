import time

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed, RateLimited
from app.core.logging import redact
from app.core.security import LoginRateLimiter, create_access_token, decode_access_token, hash_password, validate_password_strength, verify_password


def test_password_hash_verify_and_limits():
    h = hash_password("Correct-Horse-9")
    assert h != "Correct-Horse-9" and verify_password("Correct-Horse-9", h) and not verify_password("wrong", h)
    with pytest.raises(ValueError):
        hash_password("x" * 80)
    with pytest.raises(ValueError):
        validate_password_strength("short")
    with pytest.raises(ValueError):
        validate_password_strength("alllowercase123")


def test_jwt_roundtrip_and_tamper():
    s = Settings(_env_file=None, secret_key="k" * 40)
    tok = create_access_token(s, "u1", "admin")
    assert decode_access_token(s, tok)["sub"] == "u1"
    with pytest.raises(AuthenticationFailed):
        decode_access_token(s, tok + "x")
    with pytest.raises(AuthenticationFailed):
        decode_access_token(Settings(_env_file=None, secret_key="z" * 40), tok)


def test_rate_limiter_blocks_then_resets():
    lim = LoginRateLimiter(2, 60)
    lim.record_failure("k")
    lim.record_failure("k")
    with pytest.raises(RateLimited):
        lim.check("k")
    lim.reset("k")
    lim.check("k")


def test_rate_limiter_window_expires():
    lim = LoginRateLimiter(1, 0)
    lim.record_failure("k")
    time.sleep(0.01)
    lim.check("k")


def test_production_rejects_weak_config():
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production", secret_key="CHANGE_ME_TO_A_LONG_RANDOM_VALUE")
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production", secret_key="k" * 40, allowed_origins="*")
    Settings(_env_file=None, app_env="production", secret_key="k" * 40)


def test_log_redaction():
    assert "abc123" not in redact("Authorization: Bearer abc123")
    assert "secretval" not in redact('{"api_key": "secretval"}')
    assert "AIzaSyA" not in redact("key AIzaSyA1234567890123456789012")
