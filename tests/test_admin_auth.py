import pytest
from fastapi import HTTPException

from app import main


def test_admin_write_fails_closed_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")

    with pytest.raises(HTTPException) as error:
        main.require_admin("")

    assert error.value.status_code == 503


def test_admin_write_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "expected-secret-token")

    for supplied in (None, "", "wrong-token"):
        with pytest.raises(HTTPException) as error:
            main.require_admin(supplied)

        assert error.value.status_code == 401


def test_admin_write_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "expected-secret-token")

    assert main.require_admin("expected-secret-token") is None
