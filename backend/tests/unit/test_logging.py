import json
import logging

from app.core.logging import JsonFormatter, redact


def test_redacts_secrets_and_pii():
    data = redact(
        {
            "access_token": "abc",
            "email": "user@example.com",
            "status_code": 200,
            "note": "звоните +7 (999) 123-45-67 или user@example.com, Bearer abc.def",
        }
    )
    assert data["access_token"] == "***"
    assert data["email"] == "***"
    assert data["status_code"] == 200
    assert "999" not in data["note"] and "user@example.com" not in data["note"] and "abc.def" not in data["note"]


def test_formatter_redacts_message():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "token url ?code=XYZ&access_token=SECRET", (), None)
    out = json.loads(JsonFormatter().format(record))
    assert "SECRET" not in out["msg"] and "XYZ" not in out["msg"]
