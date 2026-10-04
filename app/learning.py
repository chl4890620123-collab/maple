from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import pstdev

from .db import connection


DEFAULT_WINDOW_DAYS = 90
MIN_RATIO = 0.25
MAX_RATIO = 1.50


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _since_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _outcome_index(days: int) -> dict[str, dict]:
    since = _since_iso(days)
    sales_by_item: dict[str, list[dict]] = defaultdict(list)
    crafts_by_item: dict[str, dict] = defaultdict(lambda: {"craft_count": 0, "crafted_quantity": 0.0})

    with connection() as conn:
        sales = conn.execute(
            """SELECT i.name AS item_name,
                      sh.quantity AS sold_quantity,
                      sh.realized_profit,
                      ch.quantity AS craft_quantity,
                      ch.expected_profit_snapshot
               FROM sales_history sh
               JOIN items i ON i.id = sh.item_id
               LEFT JOIN craft_history ch ON ch.id = sh.craft_id
               WHERE sh.sold_at >= ?""",
            (since,),
        ).fetchall()
        crafts = conn.execute(
            """SELECT i.name AS item_name, ch.quantity
               FROM craft_history ch
               JOIN items i ON i.id = ch.item_id
               WHERE ch.crafted_at >= ?""",
            (since,),
        ).fetchall()

    for row in sales:
        sales_by_item[row["item_name"]].append(dict(row))
    for row in crafts:
        bucket = crafts_by_item[row["item_name"]]
        bucket["craft_count"] += 1
        bucket["crafted_quantity"] += float(row["quantity"] or 0)

    result = {}
    for item_name in set(sales_by_item) | set(crafts_by_item):
        sales = sales_by_item.get(item_name, [])
        craft_stats = crafts_by_item.get(item_name, {"craft_count": 0, "crafted_quantity": 0.0})
        sold_quantity = sum(float(row["sold_quantity"] or 0) for row in sales)
        predicted_profit = 0.0
        realized_profit = 0.0
        comparable_sales = 0

        for row in sales:
            craft_quantity = float(row["craft_quantity"] or 0)
            expected_total = float(row["expected_profit_snapshot"] or 0)
            sold = float(row["sold_quantity"] or 0)
            if craft_quantity <= 0 or expected_total <= 0 or sold <= 0:
                continue
            predicted_profit += (expected_total / craft_quantity) * sold
            realized_profit += float(row["realized_profit"] or 0)
            comparable_sales += 1

        ratio = realized_profit / predicted_profit if predicted_profit > 0 else 1.0
        crafted_quantity = float(craft_stats["crafted_quantity"] or 0)
        sell_through = _clamp(sold_quantity / crafted_quantity, 0.0, 1.0) if crafted_quantity > 0 else 1.0

        result[item_name] = {
            "sample_count": comparable_sales,
            "sale_count": len(sales),
            "craft_count": int(craft_stats["craft_count"]),
            "crafted_quantity": crafted_quantity,
            "sold_quantity": sold_quantity,
            "realization_ratio": ratio,
            "sell_through_rate": sell_through,
        }
    return result


def _price_history_index(days: int) -> dict[str, dict]:
    since = _since_iso(days)
    try:
        with connection() as conn:
            rows = conn.execute(
                """SELECT item_name, price
                   FROM market_price_history
                   WHERE recorded_at >= ? AND price > 0
                   ORDER BY item_name, recorded_at""",
                (since,),
            ).fetchall()
    except Exception:
        return {}

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["item_name"]].append(float(row["price"]))

    result = {}
    for item_name, prices in grouped.items():
        mean = sum(prices) / len(prices)
        volatility = (pstdev(prices) / mean) if len(prices) >= 2 and mean > 0 else 0.0
        result[item_name] = {
            "price_point_count": len(prices),
            "price_volatility": volatility,
        }
    return result


def _match_item_name(row: dict, outcomes: dict[str, dict], price_history: dict[str, dict]) -> str:
    names = [str(row.get("name") or "")]
    outputs = sorted(
        row.get("outputs") or [],
        key=lambda item: float(item.get("expected_gross") or 0),
        reverse=True,
    )
    names.extend(str(item.get("item_name") or "") for item in outputs)

    for name in names:
        if name in outcomes:
            return name
    for name in names:
        if name in price_history:
            return name
    return names[0] if names else ""


def apply_learning(rows: list[dict], days: int = DEFAULT_WINDOW_DAYS) -> list[dict]:
    """Attach experience-based recommendation fields without mutating raw profit math.

    The deterministic craft-profit calculation remains the source of truth. This layer
    only re-ranks profitable recipes using observed prediction accuracy, sell-through,
    and recorded market-price volatility. With no history, the adjusted value is exactly
    the original expected profit.
    """
    outcomes = _outcome_index(days)
    price_history = _price_history_index(days)
    learned_rows = []

    for original in rows:
        row = dict(original)
        raw_profit = row.get("expected_profit")
        matched_name = _match_item_name(row, outcomes, price_history)
        outcome = outcomes.get(matched_name, {})
        price = price_history.get(matched_name, {})

        sample_count = int(outcome.get("sample_count", 0))
        experience_confidence = _clamp(sample_count / 8.0, 0.0, 1.0)
        empirical_ratio = _clamp(float(outcome.get("realization_ratio", 1.0)), MIN_RATIO, MAX_RATIO)
        calibrated_ratio = 1.0 + experience_confidence * (empirical_ratio - 1.0)

        craft_count = int(outcome.get("craft_count", 0))
        sell_through = _clamp(float(outcome.get("sell_through_rate", 1.0)), 0.0, 1.0)
        liquidity_factor = 1.0
        if craft_count > 0:
            liquidity_factor = 1.0 - experience_confidence * (1.0 - sell_through) * 0.25

        price_points = int(price.get("price_point_count", 0))
        volatility = max(0.0, float(price.get("price_volatility", 0.0)))
        volatility_confidence = _clamp((price_points - 1) / 8.0, 0.0, 1.0)
        volatility_penalty = min(0.20, volatility * 0.25) * volatility_confidence
        volatility_factor = 1.0 - volatility_penalty

        factor = _clamp(calibrated_ratio * liquidity_factor * volatility_factor, 0.30, 1.50)
        if raw_profit is None:
            adjusted_profit = None
        elif float(raw_profit) <= 0:
            adjusted_profit = float(raw_profit)
        else:
            adjusted_profit = float(raw_profit) * factor

        confidence_score = round(
            min(100.0, sample_count * 10.0 + min(price_points, 10) * 2.0),
            1,
        )
        if sample_count >= 5:
            state = "learned"
        elif sample_count > 0 or price_points >= 3:
            state = "warming"
        else:
            state = "collecting"

        if sample_count > 0:
            realized_pct = empirical_ratio * 100
            explanation = (
                f"최근 {days}일 실제 판매 {sample_count}건에서 예상 대비 실현수익 "
                f"{realized_pct:.0f}%, 판매율 {sell_through * 100:.0f}%를 반영했습니다."
            )
        elif price_points >= 3:
            explanation = (
                f"실제 판매 표본은 아직 부족하지만 최근 {days}일 시세 {price_points}건의 "
                f"변동성을 위험 보정에 반영했습니다."
            )
        else:
            explanation = "실제 제작·판매 기록이 더 쌓이면 추천값을 자동으로 보정합니다."

        row["learning"] = {
            "window_days": days,
            "matched_item_name": matched_name,
            "state": state,
            "sample_count": sample_count,
            "price_point_count": price_points,
            "confidence_score": confidence_score,
            "realization_ratio": round(float(outcome.get("realization_ratio", 1.0)), 4),
            "sell_through_rate": round(sell_through, 4),
            "price_volatility": round(volatility, 4),
            "adjustment_factor": round(factor, 4),
            "adjusted_expected_profit": round(adjusted_profit, 2) if adjusted_profit is not None else None,
            "explanation": explanation,
        }
        learned_rows.append(row)

    return learned_rows
