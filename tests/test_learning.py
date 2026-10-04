import os
import tempfile

from datetime import datetime, timezone


def _configure_sqlite(db_path: str):
    os.environ["DB_ENGINE"] = "sqlite"
    os.environ["DB_PATH"] = db_path
    from app import config

    config.DB_ENGINE = "sqlite"
    config.DB_PATH = db_path

    from app import db, learning

    return db, learning


def _learning_row(name: str, expected_profit: float = 1000.0):
    return {
        "name": name,
        "expected_profit": expected_profit,
        "price_complete": True,
        "outputs": [
            {
                "item_name": name,
                "expected_gross": 2000.0,
            }
        ],
    }


def _record_outcome(db, item_name: str, expected_profit: float, realized_profit: float):
    ts = datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        item = conn.execute("SELECT id FROM items WHERE name=?", (item_name,)).fetchone()
        assert item is not None
        item_id = item["id"]
        craft = conn.execute(
            """INSERT INTO craft_history(
                   item_id, quantity, unit_cost_snapshot, sale_price_snapshot,
                   expected_profit_snapshot, fee_rate_snapshot, crafted_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, 1.0, 1000.0, 2100.0, expected_profit, 0.05, ts, "learning-test"),
        )
        conn.execute(
            """INSERT INTO sales_history(
                   craft_id, item_id, quantity, unit_sale_price, unit_cost_snapshot,
                   fee_rate, realized_profit, sold_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (craft.lastrowid, item_id, 1.0, 1600.0, 1000.0, 0.05, realized_profit, ts, "learning-test"),
        )


def test_learning_is_neutral_without_history():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning = _configure_sqlite(os.path.join(temp_dir, "neutral.db"))
        db.init_db()

        result = learning.apply_learning([_learning_row("마이스터링")], days=3650)[0]
        assert result["learning"]["state"] == "collecting"
        assert result["learning"]["sample_count"] == 0
        assert result["learning"]["adjustment_factor"] == 1.0
        assert result["learning"]["adjusted_expected_profit"] == 1000.0


def test_learning_penalizes_repeated_underperformance():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning = _configure_sqlite(os.path.join(temp_dir, "under.db"))
        db.init_db()

        for _ in range(8):
            _record_outcome(db, "마이스터링", expected_profit=1000.0, realized_profit=500.0)

        result = learning.apply_learning([_learning_row("마이스터링")], days=3650)[0]
        assert result["learning"]["state"] == "learned"
        assert result["learning"]["sample_count"] == 8
        assert result["learning"]["confidence_score"] >= 80
        assert result["learning"]["realization_ratio"] == 0.5
        assert result["learning"]["adjusted_expected_profit"] == 500.0


def test_learning_rewards_repeated_outperformance():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning = _configure_sqlite(os.path.join(temp_dir, "over.db"))
        db.init_db()

        for _ in range(8):
            _record_outcome(db, "마이스터링", expected_profit=1000.0, realized_profit=1400.0)

        result = learning.apply_learning([_learning_row("마이스터링")], days=3650)[0]
        assert result["learning"]["state"] == "learned"
        assert result["learning"]["realization_ratio"] == 1.4
        assert result["learning"]["adjusted_expected_profit"] == 1400.0


def test_learning_never_changes_negative_profit_into_a_recommendation():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning = _configure_sqlite(os.path.join(temp_dir, "negative.db"))
        db.init_db()

        for _ in range(8):
            _record_outcome(db, "마이스터링", expected_profit=1000.0, realized_profit=1400.0)

        result = learning.apply_learning([_learning_row("마이스터링", expected_profit=-100.0)], days=3650)[0]
        assert result["learning"]["adjusted_expected_profit"] == -100.0
