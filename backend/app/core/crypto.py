"""Authenticated encryption for secrets at rest (OAuth tokens, AI keys).

Format: ``v1.<key_id>.<base64(nonce|ciphertext)>`` with AES-256-GCM.
The first configured key encrypts; every configured key can decrypt, which allows rotation.
"""

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CryptoError(Exception):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _decode_key(raw: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as exc:
        raise CryptoError("encryption key is not valid base64") from exc
    if len(key) != 32:
        raise CryptoError("encryption key must decode to 32 bytes")
    return key


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


class SecretBox:
    def __init__(self, raw_keys: list[str]):
        if not raw_keys:
            raise CryptoError("ENCRYPTION_KEYS is not configured")
        self._keys = [_decode_key(k) for k in raw_keys]
        self._by_id = {_key_id(k): k for k in self._keys}

    def encrypt(self, plaintext: str, associated_data: str = "") -> str:
        key = self._keys[0]
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, plaintext.encode(), associated_data.encode() or None)
        return f"v1.{_key_id(key)}.{base64.urlsafe_b64encode(nonce + ct).decode()}"

    def decrypt(self, token: str, associated_data: str = "") -> str:
        try:
            version, kid, payload = token.split(".", 2)
        except ValueError as exc:
            raise CryptoError("malformed ciphertext") from exc
        if version != "v1" or kid not in self._by_id:
            raise CryptoError("unknown key or version")
        blob = base64.urlsafe_b64decode(payload)
        try:
            pt = AESGCM(self._by_id[kid]).decrypt(blob[:12], blob[12:], associated_data.encode() or None)
        except Exception as exc:  # cryptography raises InvalidTag
            raise CryptoError("decryption failed") from exc
        return pt.decode()

    def needs_rotation(self, token: str) -> bool:
        return not token.startswith(f"v1.{_key_id(self._keys[0])}.")


_box: SecretBox | None = None


def get_box() -> SecretBox:
    global _box
    if _box is None:
        _box = SecretBox(get_settings().encryption_key_list())
    return _box


def reset_box() -> None:
    global _box
    _box = None


def token_hash(value: str) -> str:
    """Stable hash for lookup of random tokens (sessions, link codes). Not for passwords."""
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
