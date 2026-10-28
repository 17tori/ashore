import base64

import pytest

from app.core.crypto import CryptoError, SecretBox, generate_key, token_hash


def test_roundtrip_and_associated_data():
    box = SecretBox([generate_key()])
    token = box.encrypt("access-token-value", "hh:access:u1")
    assert token.startswith("v1.")
    assert "access-token-value" not in token
    assert box.decrypt(token, "hh:access:u1") == "access-token-value"
    with pytest.raises(CryptoError):
        box.decrypt(token, "hh:access:u2")  # bound to its owner: cannot be swapped between users


def test_tampering_detected():
    box = SecretBox([generate_key()])
    token = box.encrypt("secret")
    head, kid, payload = token.split(".", 2)
    raw = bytearray(base64.urlsafe_b64decode(payload))
    raw[-1] ^= 1
    with pytest.raises(CryptoError):
        box.decrypt(f"{head}.{kid}.{base64.urlsafe_b64encode(bytes(raw)).decode()}")


def test_key_rotation():
    old, new = generate_key(), generate_key()
    token = SecretBox([old]).encrypt("v")
    rotated = SecretBox([new, old])
    assert rotated.decrypt(token) == "v"
    assert rotated.needs_rotation(token)
    assert not rotated.needs_rotation(rotated.encrypt("v"))
    with pytest.raises(CryptoError):
        SecretBox([new]).decrypt(token)


def test_bad_keys_rejected():
    with pytest.raises(CryptoError):
        SecretBox([])
    with pytest.raises(CryptoError):
        SecretBox([base64.urlsafe_b64encode(b"short").decode()])


def test_token_hash_stable():
    assert token_hash("a") == token_hash("a") != token_hash("b")
