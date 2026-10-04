import os
import tempfile
from datetime import datetime, timedelta, timezone


def _configure_sqlite(db_path: str):
    os.environ["DB_ENGINE"] = "sqlite"
    os.environ["DB_PATH"] = db_path

    from app import config
    config.DB_ENGINE = "sqlite"
    config.DB_PATH = db_path

    from app import db, learning, meister_history
    return db, learning, meister_history


def _row(
    recipe_key: str = "test:recipe",
    raw_profit: float = 100.0,
    candidate_profit: float = 200.0,
    input_cost: float = 100.0,
):
    return {
        "recipe_key": recipe_key,
        "name": "테스트 레시피",
        "price_complete": True,
        "expected_profit": raw_profit,
        "input_cost": input_cost,
        "outputs": [{"item_name": "테스트 결과물", "expected_gross": 300.0}],
        "learning": {
            "candidate_adjusted_expected_profit": candidate_profit,
            "adjusted_expected_profit": candidate_profit,
            "confidence_score": 50.0,
        },
    }


def _gross_for_profit(input_cost: float, realized_profit: float, fee_rate: float = 0.05) -> float:
    return (input_cost + realized_profit) / (1 - fee_rate)


def test_recipe_key_flow_records_sale_time_and_feeds_learning():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning, history = _configure_sqlite(os.path.join(temp_dir, "flow.db"))
        db.init_db()

        craft = history.record_craft(_row(), quantity=2, rank_position=3)
        assert craft["recipe_key"] == "test:recipe"
        assert craft["input_cost_snapshot"] == 200.0
        assert craft["raw_expected_profit_snapshot"] == 200.0
        assert craft["candidate_expected_profit_snapshot"] == 400.0

        two_days_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with db.connection() as conn:
            conn.execute(
                "UPDATE meister_craft_history SET crafted_at=? WHERE id=?",
                (two_days_ago, craft["id"]),
            )

        sale = history.record_sale(
            craft["id"],
            gross_sale_amount=_gross_for_profit(200.0, 220.0),
            fee_rate=0.05,
        )
        assert round(sale["realized_profit"], 2) == 220.0
        assert sale["time_to_sell_hours"] >= 47.9

        learned = learning.apply_learning([_row(raw_profit=100.0, candidate_profit=100.0)], days=90)[0]
        assert learned["learning"]["outcome_source"] == "recipe_key"
        assert learned["learning"]["sample_count"] == 1
        assert learned["learning"]["avg_sell_hours"] >= 47.9
        assert learned["learning"]["daily_capital_roi"] is not None


def test_backtest_rolls_back_candidate_when_it_is_worse():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning, history = _configure_sqlite(os.path.join(temp_dir, "rollback.db"))
        db.init_db()

        for _ in range(5):
            craft = history.record_craft(_row(raw_profit=100.0, candidate_profit=300.0), quantity=1)
            history.record_sale(
                craft["id"],
                gross_sale_amount=_gross_for_profit(100.0, 100.0),
                fee_rate=0.05,
            )

        result = learning.backtest(days=180)
        assert result["sample_count"] == 5
        assert result["state"] == "rolled_back"
        assert result["policy_enabled"] is False
        assert result["candidate_mae"] > result["raw_mae"]

        learned = learning.apply_learning([_row(raw_profit=100.0, candidate_profit=300.0)], days=90)[0]
        assert learned["learning"]["policy_state"] == "rolled_back"
        assert learned["learning"]["adjusted_expected_profit"] == 100.0


def test_backtest_promotes_candidate_when_it_is_better():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, learning, history = _configure_sqlite(os.path.join(temp_dir, "promote.db"))
        db.init_db()

        for _ in range(5):
            craft = history.record_craft(_row(raw_profit=100.0, candidate_profit=200.0), quantity=1)
            history.record_sale(
                craft["id"],
                gross_sale_amount=_gross_for_profit(100.0, 200.0),
                fee_rate=0.05,
            )

        result = learning.backtest(days=180)
        assert result["sample_count"] == 5
        assert result["state"] == "promoted"
        assert result["policy_enabled"] is True
        assert result["candidate_mae"] < result["raw_mae"]
        assert result["improvement_pct"] > 0
