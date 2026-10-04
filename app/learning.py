from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import pstdev

from .db import connection
from . import meister_history


DEFAULT_WINDOW_DAYS = 90
MIN_RATIO = 0.25
MAX_RATIO = 1.50
BACKTEST_MIN_SAMPLES = 5
BACKTEST_PROMOTION_MARGIN = 0.02
RECENCY_HALF_LIFE_DAYS = 14.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _since_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _age_days(timestamp: str) -> float:
    try:
        dt = datetime.fromisoformat(timestamp).astimezone(timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except Exception:
        return 0.0


def _weight(timestamp: str) -> float:
    return 0.5 ** (_age_days(timestamp) / RECENCY_HALF_LIFE_DAYS)


def _legacy_outcome_index(days: int) -> dict[str, dict]:
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
            "realization_ratio": ratio,
            "sell_through_rate": sell_through,
            "avg_sell_hours": None,
            "daily_capital_roi": None,
            "source": "legacy",
        }
    return result


def _direct_outcome_index(days: int) -> dict[str, dict]:
    since = _since_iso(days)
    completed = meister_history.completed_outcomes(since)
    open_counts = meister_history.open_craft_counts(since)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in completed:
        grouped[row["recipe_key"]].append(row)

    result = {}
    for recipe_key in set(grouped) | set(open_counts):
        rows = grouped.get(recipe_key, [])
        total_weight = 0.0
        weighted_ratio = 0.0
        weighted_hours = 0.0
        weighted_daily_roi = 0.0
        completed_count = 0

        for row in rows:
            raw = float(row["raw_expected_profit_snapshot"] or 0)
            capital = float(row["input_cost_snapshot"] or 0)
            actual = float(row["realized_profit"] or 0)
            if raw <= 0:
                continue
            weight = _weight(row["sold_at"])
            crafted_at = datetime.fromisoformat(row["crafted_at"]).astimezone(timezone.utc)
            sold_at = datetime.fromisoformat(row["sold_at"]).astimezone(timezone.utc)
            hours = max((sold_at - crafted_at).total_seconds() / 3600, 0.25)
            daily_roi = (actual / capital) / max(hours / 24.0, 0.25) if capital > 0 else 0.0
            total_weight += weight
            weighted_ratio += (actual / raw) * weight
            weighted_hours += hours * weight
            weighted_daily_roi += daily_roi * weight
            completed_count += 1

        open_count = int(open_counts.get(recipe_key, 0))
        total_crafts = completed_count + open_count
        if total_weight > 0:
            realization_ratio = weighted_ratio / total_weight
            avg_sell_hours = weighted_hours / total_weight
            daily_capital_roi = weighted_daily_roi / total_weight
        else:
            realization_ratio = 1.0
            avg_sell_hours = None
            daily_capital_roi = None

        result[recipe_key] = {
            "sample_count": completed_count,
            "sale_count": completed_count,
            "craft_count": total_crafts,
            "realization_ratio": realization_ratio,
            "sell_through_rate": completed_count / total_crafts if total_crafts else 1.0,
            "avg_sell_hours": avg_sell_hours,
            "daily_capital_roi": daily_capital_roi,
            "source": "recipe_key",
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
        result[item_name] = {"price_point_count": len(prices), "price_volatility": volatility}
    return result


def backtest(days: int = 180) -> dict:
    rows = meister_history.completed_outcomes(_since_iso(days))
    comparable = [row for row in rows if row["raw_expected_profit_snapshot"] is not None]
    if not comparable:
        return {
            "days": days,
            "sample_count": 0,
            "raw_mae": None,
            "candidate_mae": None,
            "improvement_pct": None,
            "policy_enabled": True,
            "state": "collecting",
        }

    raw_error = 0.0
    candidate_error = 0.0
    for row in comparable:
        actual = float(row["realized_profit"] or 0)
        raw_error += abs(actual - float(row["raw_expected_profit_snapshot"] or 0))
        candidate_error += abs(actual - float(row["candidate_expected_profit_snapshot"] or 0))

    count = len(comparable)
    raw_mae = raw_error / count
    candidate_mae = candidate_error / count
    improvement = ((raw_mae - candidate_mae) / raw_mae * 100) if raw_mae > 0 else 0.0
    enough = count >= BACKTEST_MIN_SAMPLES
    enabled = not enough or candidate_mae <= raw_mae * (1 - BACKTEST_PROMOTION_MARGIN)
    state = "promoted" if enough and enabled else "rolled_back" if enough else "observing"
    return {
        "days": days,
        "sample_count": count,
        "raw_mae": round(raw_mae, 2),
        "candidate_mae": round(candidate_mae, 2),
        "improvement_pct": round(improvement, 2),
        "policy_enabled": enabled,
        "state": state,
    }


def _match_item_name(row: dict, legacy: dict[str, dict], price_history: dict[str, dict]) -> str:
    names = [str(row.get("name") or "")]
    outputs = sorted(row.get("outputs") or [], key=lambda item: float(item.get("expected_gross") or 0), reverse=True)
    names.extend(str(item.get("item_name") or "") for item in outputs)
    for name in names:
        if name in legacy:
            return name
    for name in names:
        if name in price_history:
            return name
    return names[0] if names else ""


def apply_learning(rows: list[dict], days: int = DEFAULT_WINDOW_DAYS) -> list[dict]:
    direct = _direct_outcome_index(days)
    legacy = _legacy_outcome_index(days)
    price_history = _price_history_index(days)
    policy = backtest(max(days, 180))
    learned_rows = []

    for original in rows:
        row = dict(original)
        raw_profit = row.get("expected_profit")
        recipe_key = str(row.get("recipe_key") or "")
        matched_name = _match_item_name(row, legacy, price_history)
        outcome = direct.get(recipe_key) or legacy.get(matched_name, {})
        price = price_history.get(matched_name, {})

        sample_count = int(outcome.get("sample_count", 0))
        confidence = _clamp(sample_count / 8.0, 0.0, 1.0)
        empirical_ratio = _clamp(float(outcome.get("realization_ratio", 1.0)), MIN_RATIO, MAX_RATIO)
        calibrated_ratio = 1.0 + confidence * (empirical_ratio - 1.0)

        craft_count = int(outcome.get("craft_count", 0))
        sell_through = _clamp(float(outcome.get("sell_through_rate", 1.0)), 0.0, 1.0)
        liquidity_factor = 1.0
        if craft_count > 0:
            liquidity_factor = 1.0 - confidence * (1.0 - sell_through) * 0.25

        avg_sell_hours = outcome.get("avg_sell_hours")
        velocity_factor = 1.0
        if avg_sell_hours is not None and confidence > 0:
            hours = float(avg_sell_hours)
            if hours <= 24:
                velocity_factor = 1.0 + 0.05 * confidence
            elif hours >= 168:
                velocity_factor = 1.0 - 0.10 * confidence
            else:
                velocity_factor = 1.0 - ((hours - 24) / 144.0) * 0.10 * confidence

        price_points = int(price.get("price_point_count", 0))
        volatility = max(0.0, float(price.get("price_volatility", 0.0)))
        volatility_confidence = _clamp((price_points - 1) / 8.0, 0.0, 1.0)
        volatility_factor = 1.0 - min(0.20, volatility * 0.25) * volatility_confidence

        factor = _clamp(calibrated_ratio * liquidity_factor * velocity_factor * volatility_factor, 0.30, 1.50)
        if raw_profit is None:
            candidate_profit = None
        elif float(raw_profit) <= 0:
            candidate_profit = float(raw_profit)
        else:
            candidate_profit = float(raw_profit) * factor

        active_profit = candidate_profit if policy["policy_enabled"] else raw_profit
        confidence_score = round(min(100.0, sample_count * 10.0 + min(price_points, 10) * 2.0), 1)
        if sample_count >= 5:
            state = "learned"
        elif sample_count > 0 or price_points >= 3:
            state = "warming"
        else:
            state = "collecting"

        if sample_count > 0:
            speed_text = f", 평균 판매 {float(avg_sell_hours):.1f}시간" if avg_sell_hours is not None else ""
            explanation = (
                f"최근 {days}일 실제 결과 {sample_count}건에서 예상 대비 실현수익 "
                f"{empirical_ratio * 100:.0f}%, 판매율 {sell_through * 100:.0f}%{speed_text}를 반영했습니다."
            )
        elif price_points >= 3:
            explanation = f"실제 판매 표본은 부족하지만 최근 {days}일 시세 {price_points}건의 변동성을 반영했습니다."
        else:
            explanation = "제작 시작과 실제 판매를 기록하면 recipe_key 기준으로 추천을 자동 보정합니다."

        if not policy["policy_enabled"]:
            explanation += " 현재 후보 보정식이 백테스트에서 원본 계산보다 나빠 자동 롤백되어 원본 예상수익을 사용합니다."

        row["learning"] = {
            "window_days": days,
            "matched_item_name": matched_name,
            "outcome_source": outcome.get("source", "none"),
            "state": state,
            "sample_count": sample_count,
            "price_point_count": price_points,
            "confidence_score": confidence_score,
            "realization_ratio": round(float(outcome.get("realization_ratio", 1.0)), 4),
            "sell_through_rate": round(sell_through, 4),
            "avg_sell_hours": round(float(avg_sell_hours), 2) if avg_sell_hours is not None else None,
            "daily_capital_roi": round(float(outcome["daily_capital_roi"]) * 100, 4) if outcome.get("daily_capital_roi") is not None else None,
            "price_volatility": round(volatility, 4),
            "adjustment_factor": round(factor, 4),
            "candidate_adjusted_expected_profit": round(candidate_profit, 2) if candidate_profit is not None else None,
            "adjusted_expected_profit": round(float(active_profit), 2) if active_profit is not None else None,
            "policy_state": policy["state"],
            "policy_enabled": policy["policy_enabled"],
            "explanation": explanation,
        }
        learned_rows.append(row)

    return learned_rows
