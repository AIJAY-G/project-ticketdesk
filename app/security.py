import os
import hmac
import hashlib
import secrets
import base64
import json
import time
import logging

logger = logging.getLogger(__name__)

# Secret key for HMAC token signing (at least 256 bits)
# In production, this MUST be set via the SECRET_KEY or JWT_SECRET environment variable.
_env_secret = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET")
if _env_secret and _env_secret.strip():
    SECRET_KEY = _env_secret.strip()
else:
    # Stable fallback for local dev / tests if unset
    SECRET_KEY = "ticketdesk-local-dev-secret-key-change-in-production-min32bytes!"

TOKEN_EXPIRATION_SECONDS = int(os.getenv("TOKEN_EXPIRATION_SECONDS", "86400"))  # 24 hours


def hash_password(plain_password: str) -> str:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and a 16-byte random salt.
    OWASP and NIST SP 800-132 recommended standard.
    Format: pbkdf2_sha256$<iterations>$<hex_salt>$<hex_hash>
    """
    if not plain_password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    iterations = 100000
    derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, stored_password: str) -> bool:
    """
    Verifies a plain password against the stored password hash using constant-time comparison.
    Supports legacy plaintext migration checking.
    """
    if not plain_password or not stored_password:
        return False

    # Standard PBKDF2-SHA256 format check
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            parts = stored_password.split("$")
            if len(parts) != 4:
                return False
            _, iterations_str, salt_hex, expected_hex = parts
            iterations = int(iterations_str)
            salt = bytes.fromhex(salt_hex)
            expected_key = bytes.fromhex(expected_hex)
            derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(derived, expected_key)
        except Exception as e:
            logger.error("Error during password hash verification: %s", e)
            return False

    # Legacy plaintext fallback for backwards compatibility during database migration
    return hmac.compare_digest(plain_password.encode("utf-8"), stored_password.encode("utf-8"))


def create_access_token(payload_data: dict, expires_in: int = TOKEN_EXPIRATION_SECONDS) -> str:
    """
    Generates an RFC 7519 compliant JSON Web Token (JWT) signed with HMAC-SHA256 (HS256).
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = payload_data.copy()
    payload["iat"] = now
    payload["exp"] = now + expires_in

    header_json = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    header_b64 = base64.urlsafe_b64encode(header_json).decode("utf-8").rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_access_token(token: str) -> dict | None:
    """
    Verifies an HS256 JWT signature and expiration.
    Returns the decoded payload dict if valid, or None if invalid or expired.
    """
    if not token or not isinstance(token, str):
        return None

    parts = token.strip().split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts

    # Step 1: Verify HMAC signature using constant-time comparison
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        pad_sig = len(sig_b64) % 4
        sig_bytes = base64.urlsafe_b64decode(sig_b64 + ("=" * (4 - pad_sig) if pad_sig else ""))
        if not hmac.compare_digest(sig_bytes, expected_sig):
            return None
    except Exception:
        return None

    # Step 2: Decode payload and verify expiration
    try:
        pad_payload = len(payload_b64) % 4
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + ("=" * (4 - pad_payload) if pad_payload else ""))
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Verify expiration
        exp = payload.get("exp")
        if not exp or int(exp) < int(time.time()):
            return None

        return payload
    except Exception:
        return None
