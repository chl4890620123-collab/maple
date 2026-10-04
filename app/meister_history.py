from __future__ import annotations

from datetime import datetime, timezone

from . import config
from .db import connection, now_iso


def init_tables() -> None:
    with connection() as conn:
        if config.DB_ENGINE == "mariadb":
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_recommendation_history (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    recipe_key VARCHAR(255) NOT NULL,
                    recipe_name VARCHAR(255) NOT NULL,
                    raw_expected_profit DOUBLE NOT NULL,
                    candidate_expected_profit DOUBLE NOT NULL,
                    active_expected_profit DOUBLE NOT NULL,
                    input_cost DOUBLE NOT NULL,
                    confidence_score DOUBLE NOT NULL DEFAULT 0,
                    rank_position INT NULL,
                    recommended_at VARCHAR(40) NOT NULL,
                    KEY idx_meister_recommendation_recipe_time (recipe_key, recommended_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_craft_history (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    recommendation_id BIGINT UNSIGNED NULL,
                    recipe_key VARCHAR(255) NOT NULL,
                    recipe_name VARCHAR(255) NOT NULL,
                    quantity DOUBLE NOT NULL,
                    input_cost_snapshot DOUBLE NOT NULL,
                    raw_expected_profit_snapshot DOUBLE NOT NULL,
                    candidate_expected_profit_snapshot DOUBLE NOT NULL,
                    active_expected_profit_snapshot DOUBLE NOT NULL,
                    crafted_at VARCHAR(40) NOT NULL,
                    note TEXT NULL,
                    KEY idx_meister_craft_recipe_time (recipe_key, crafted_at),
                    CONSTRAINT fk_meister_craft_recommendation
                        FOREIGN KEY (recommendation_id) REFERENCES meister_recommendation_history(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_sale_history (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    craft_id BIGINT UNSIGNED NOT NULL UNIQUE,
                    recipe_key VARCHAR(255) NOT NULL,
                    gross_sale_amount DOUBLE NOT NULL,
                    fee_rate DOUBLE NOT NULL,
                    realized_profit DOUBLE NOT NULL,
                    sold_at VARCHAR(40) NOT NULL,
                    note TEXT NULL,
                    KEY idx_meister_sale_recipe_time (recipe_key, sold_at),
                    CONSTRAINT fk_meister_sale_craft
                        FOREIGN KEY (craft_id) REFERENCES meister_craft_history(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
        else:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_key TEXT NOT NULL,
                    recipe_name TEXT NOT NULL,
                    raw_expected_profit REAL NOT NULL,
                    candidate_expected_profit REAL NOT NULL,
                    active_expected_profit REAL NOT NULL,
                    input_cost REAL NOT NULL,
                    confidence_score REAL NOT NULL DEFAULT 0,
                    rank_position INTEGER,
                    recommended_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meister_recommendation_recipe_time "
                "ON meister_recommendation_history(recipe_key, recommended_at)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_craft_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id INTEGER,
                    recipe_key TEXT NOT NULL,
                    recipe_name TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    input_cost_snapshot REAL NOT NULL,
                    raw_expected_profit_snapshot REAL NOT NULL,
                    candidate_expected_profit_snapshot REAL NOT NULL,
                    active_expected_profit_snapshot REAL NOT NULL,
                    crafted_at TEXT NOT NULL,
                    note TEXT,
                    FOREIGN KEY(recommendation_id) REFERENCES meister_recommendation_history(id)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meister_craft_recipe_time "
                "ON meister_craft_history(recipe_key, crafted_at)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meister_sale_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    craft_id INTEGER NOT NULL UNIQUE,
                    recipe_key TEXT NOT NULL,
                    gross_sale_amount REAL NOT NULL CHECK(gross_sale_amount >= 0),
                    fee_rate REAL NOT NULL,
                    realized_profit REAL NOT NULL,
                    sold_at TEXT NOT NULL,
                    note TEXT,
                    FOREIGN KEY(craft_id) REFERENCES meister_craft_history(id)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meister_sale_recipe_time "
                "ON meister_sale_history(recipe_key, sold_at)"
            )


def record_craft(
    row: dict,
    quantity: float,
    rank_position: int | None = None,
    note: str | None = None,
) -> dict:
    if quantity <= 0:
        raise ValueError("제작 수량은 0보다 커야 합니다.")
    if not row.get("price_complete"):
        raise ValueError("시세가 완성되지 않은 레시피는 제작 기록을 시작할 수 없습니다.")

    raw_profit = float(row.get("expected_profit") or 0)
    input_cost = float(row.get("input_cost") or 0)
    learning = row.get("learning") or {}
    candidate_profit = float(learning.get("candidate_adjusted_expected_profit", raw_profit))
    active_profit = float(learning.get("adjusted_expected_profit", raw_profit))
    confidence = float(learning.get("confidence_score", 0))
    ts = now_iso()

    with connection() as conn:
        recommendation = conn.execute(
            """INSERT INTO meister_recommendation_history(
                   recipe_key, recipe_name, raw_expected_profit, candidate_expected_profit,
                   active_expected_profit, input_cost, confidence_score, rank_position, recommended_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["recipe_key"],
                row["name"],
                raw_profit,
                candidate_profit,
                active_profit,
                input_cost,
                confidence,
                rank_position,
                ts,
            ),
        )
        craft = conn.execute(
            """INSERT INTO meister_craft_history(
                   recommendation_id, recipe_key, recipe_name, quantity,
                   input_cost_snapshot, raw_expected_profit_snapshot,
                   candidate_expected_profit_snapshot, active_expected_profit_snapshot,
                   crafted_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recommendation.lastrowid,
                row["recipe_key"],
                row["name"],
                float(quantity),
                input_cost * float(quantity),
                raw_profit * float(quantity),
                candidate_profit * float(quantity),
                active_profit * float(quantity),
                ts,
                note,
            ),
        )
        craft_id = craft.lastrowid
        return dict(
            conn.execute(
                """SELECT id, recommendation_id, recipe_key, recipe_name, quantity,
                          input_cost_snapshot, raw_expected_profit_snapshot,
                          candidate_expected_profit_snapshot, active_expected_profit_snapshot,
                          crafted_at, note
                   FROM meister_craft_history WHERE id=?""",
                (craft_id,),
            ).fetchone()
        )


def record_sale(
    craft_id: int,
    gross_sale_amount: float,
    fee_rate: float,
    note: str | None = None,
) -> dict:
    if gross_sale_amount < 0:
        raise ValueError("실제 총 판매대금은 0 이상이어야 합니다.")

    with connection() as conn:
        craft = conn.execute(
            """SELECT id, recipe_key, recipe_name, input_cost_snapshot, crafted_at
               FROM meister_craft_history WHERE id=?""",
            (craft_id,),
        ).fetchone()
        if craft is None:
            raise ValueError("제작 기록을 찾을 수 없습니다.")
        if conn.execute("SELECT id FROM meister_sale_history WHERE craft_id=?", (craft_id,)).fetchone():
            raise ValueError("이미 판매 완료된 제작 기록입니다.")

        realized_profit = float(gross_sale_amount) * (1 - float(fee_rate)) - float(craft["input_cost_snapshot"])
        sold_at = now_iso()
        sale = conn.execute(
            """INSERT INTO meister_sale_history(
                   craft_id, recipe_key, gross_sale_amount, fee_rate, realized_profit, sold_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                craft_id,
                craft["recipe_key"],
                float(gross_sale_amount),
                float(fee_rate),
                realized_profit,
                sold_at,
                note,
            ),
        )
        result = dict(
            conn.execute(
                """SELECT id, craft_id, recipe_key, gross_sale_amount, fee_rate,
                          realized_profit, sold_at, note
                   FROM meister_sale_history WHERE id=?""",
                (sale.lastrowid,),
            ).fetchone()
        )
        result["recipe_name"] = craft["recipe_name"]
        result["crafted_at"] = craft["crafted_at"]
        result["time_to_sell_hours"] = round(
            max(
                0.0,
                (
                    datetime.fromisoformat(sold_at).astimezone(timezone.utc)
                    - datetime.fromisoformat(craft["crafted_at"]).astimezone(timezone.utc)
                ).total_seconds()
                / 3600,
            ),
            2,
        )
        return result


def recent_crafts(limit: int = 50) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT c.id, c.recommendation_id, c.recipe_key, c.recipe_name, c.quantity,
                      c.input_cost_snapshot, c.raw_expected_profit_snapshot,
                      c.candidate_expected_profit_snapshot, c.active_expected_profit_snapshot,
                      c.crafted_at, c.note,
                      s.id AS sale_id, s.gross_sale_amount, s.fee_rate, s.realized_profit, s.sold_at
               FROM meister_craft_history c
               LEFT JOIN meister_sale_history s ON s.craft_id=c.id
               ORDER BY c.crafted_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["sold"] = item["sale_id"] is not None
        item["time_to_sell_hours"] = None
        if item["sold"]:
            item["time_to_sell_hours"] = round(
                max(
                    0.0,
                    (
                        datetime.fromisoformat(item["sold_at"]).astimezone(timezone.utc)
                        - datetime.fromisoformat(item["crafted_at"]).astimezone(timezone.utc)
                    ).total_seconds()
                    / 3600,
                ),
                2,
            )
        result.append(item)
    return result


def completed_outcomes(since_iso: str) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT c.id AS craft_id, c.recipe_key, c.recipe_name, c.quantity,
                      c.input_cost_snapshot, c.raw_expected_profit_snapshot,
                      c.candidate_expected_profit_snapshot, c.active_expected_profit_snapshot,
                      c.crafted_at, s.realized_profit, s.sold_at
               FROM meister_craft_history c
               JOIN meister_sale_history s ON s.craft_id=c.id
               WHERE s.sold_at >= ?
               ORDER BY s.sold_at ASC""",
            (since_iso,),
        ).fetchall()
    return [dict(row) for row in rows]


def open_craft_counts(since_iso: str) -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT c.recipe_key, COUNT(*) AS open_count
               FROM meister_craft_history c
               LEFT JOIN meister_sale_history s ON s.craft_id=c.id
               WHERE c.crafted_at >= ? AND s.id IS NULL
               GROUP BY c.recipe_key""",
            (since_iso,),
        ).fetchall()
    return {row["recipe_key"]: int(row["open_count"]) for row in rows}
