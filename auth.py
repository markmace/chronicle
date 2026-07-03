import hashlib
import hmac


def safe_equal(a: str, b: str) -> bool:
    """Constant-time string comparison — prevents timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


def session_token(secret: str) -> str:
    """Deterministic proof that the caller once knew `secret`, for a persistent
    login cookie. Stateless — no server-side session store. Tied to `secret` so
    changing the password invalidates every cookie issued under the old one."""
    return hmac.new(secret.encode(), b"chronicle-session-v1", hashlib.sha256).hexdigest()
