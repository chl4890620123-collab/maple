import sqlite3

import pytest

from app import service


def test_legacy_database_without_market_prices_can_fallback(tmp_path, monkeypatch):
    # A pre-Meister DB can still use the original item/material price columns.
    path = tmp_path / "legacy.db"
    from app import config
    monkeypatch.setattr(config, "DB_ENGINE", "sqlite")
    monkeypatch.setattr(config, "DB_PATH", str(path))
    assert service._market_price_snapshot() == {}


def test_market_price_query_failure_is_not_misreported_as_empty_prices(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def failed_connection():
        raise sqlite3.OperationalError("database is locked")
        yield  # pragma: no cover

    monkeypatch.setattr(service, "connection", failed_connection)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        service._market_price_snapshot()
