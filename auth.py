import hmac


def safe_equal(a: str, b: str) -> bool:
    """Constant-time string comparison — prevents timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())
