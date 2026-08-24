from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import game_rules
from .db import connection, now_iso


def list_materials():
    with connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, name, current_price, active, source_note, updated_at FROM materials WHERE active=1 ORDER BY name"
        )]


def update_material_price(material_id: int, price: int):
    ts = now_iso()
    with connection() as conn:
        row = conn.execute("SELECT id FROM materials WHERE id=?", (material_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE materials SET current_price=?, updated_at=? WHERE id=?", (price, ts, material_id))
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('material', ?, ?, ?)",
            (material_id, price, ts),
        )
        return dict(conn.execute(
            "SELECT id, name, current_price, updated_at FROM materials WHERE id=?", (material_id,)
        ).fetchone())


def update_item_sale_price(item_id: int, price: int):
    ts = now_iso()
    with connection() as conn:
        row = conn.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE items SET current_sale_price=?, updated_at=? WHERE id=?", (price, ts, item_id))
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('item', ?, ?, ?)",
            (item_id, price, ts),
        )
        return dict(conn.execute(
            "SELECT id, name, current_sale_price, updated_at FROM items WHERE id=?", (item_id,)
        ).fetchone())


def calculations(fee_rate: float):
    fee_rate = game_rules.validate_auction_fee_rate(fee_rate)
    with connection() as conn:
        items = [dict(r) for r in conn.execute(
            """SELECT id, name, profession, required_rank, output_quantity, current_sale_price,
                      extra_cost, craftable, verification_status, source_note
               FROM items WHERE active=1 AND craftable=1 ORDER BY name"""
        )]
        components = [dict(r) for r in conn.execute(
            """SELECT rc.item_id, rc.quantity, m.id AS material_id, m.name AS material_name,
                      m.current_price
               FROM recipe_components rc
               JOIN materials m ON m.id=rc.material_id
               WHERE m.active=1"""
        )]

    grouped = defaultdict(list)
    for c in components:
        grouped[c["item_id"]].append(c)

    result = []
    for item in items:
        recipe_total = sum(c["quantity"] * c["current_price"] for c in grouped[item["id"]])
        batch_cost = recipe_total + item["extra_cost"]
        output_qty = float(item["output_quantity"])
        unit_cost = batch_cost / output_qty
        gross_sales = float(item["current_sale_price"]) * output_qty
        fee = gross_sales * fee_rate
        expected_profit = gross_sales - fee - batch_cost
        margin_rate = (expected_profit / gross_sales * 100) if gross_sales > 0 else 0
        roi_rate = (expected_profit / batch_cost * 100) if batch_cost > 0 else 0
        result.append({
            **item,
            "recipe_cost": round(recipe_total, 2),
            "batch_cost": round(batch_cost, 2),
            "unit_cost": round(unit_cost, 2),
            "gross_sales": round(gross_sales, 2),
            "fee": round(fee, 2),
            "expected_profit": round(expected_profit, 2),
            "margin_rate": round(margin_rate, 4),
            "roi_rate": round(roi_rate, 4),
            "recipe": grouped[item["id"]],
        })

    result.sort(key=lambda x: x["expected_profit"], reverse=True)
    for idx, row in enumerate(result, start=1):
        row["profit_rank"] = idx
    return result


def record_craft(item_id: int, quantity: float, fee_rate: float, note: str | None):
    fee_rate = game_rules.validate_auction_fee_rate(fee_rate)
    calc = next((x for x in calculations(fee_rate) if x["id"] == item_id), None)
    if calc is None:
        return None
    ts = now_iso()
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO craft_history(
                   item_id, quantity, unit_cost_snapshot, sale_price_snapshot,
                   expected_profit_snapshot, fee_rate_snapshot, crafted_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                quantity,
                calc["unit_cost"],
                calc["current_sale_price"],
                (calc["expected_profit"] / calc["output_quantity"]) * quantity,
                fee_rate,
                ts,
                note,
            ),
        )
        craft_id = cur.lastrowid
        return dict(conn.execute(
            """SELECT ch.*, i.name AS item_name FROM craft_history ch
               JOIN items i ON i.id=ch.item_id WHERE ch.id=?""",
            (craft_id,),
        ).fetchone())


def record_sale(craft_id: int | None, item_id: int, quantity: float, unit_sale_price: float, fee_rate: float, note: str | None):
    fee_rate = game_rules.validate_auction_fee_rate(fee_rate)
    with connection() as conn:
        item = conn.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            return None

        unit_cost = None
        if craft_id is not None:
            craft = conn.execute(
                "SELECT item_id, quantity, unit_cost_snapshot FROM craft_history WHERE id=?", (craft_id,)
            ).fetchone()
            if not craft or craft["item_id"] != item_id:
                return None
            already_sold = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM sales_history WHERE craft_id=?", (craft_id,)
            ).fetchone()[0]
            if float(already_sold) + float(quantity) > float(craft["quantity"]) + 1e-9:
                return None
            unit_cost = float(craft["unit_cost_snapshot"])

        if unit_cost is None:
            calc = next((x for x in calculations(fee_rate) if x["id"] == item_id), None)
            if calc is None:
                return None
            unit_cost = float(calc["unit_cost"])

        realized_profit = (unit_sale_price * (1 - fee_rate) - unit_cost) * quantity
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO sales_history(
                   craft_id, item_id, quantity, unit_sale_price, unit_cost_snapshot,
                   fee_rate, realized_profit, sold_at, note
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (craft_id, item_id, quantity, unit_sale_price, unit_cost, fee_rate, realized_profit, ts, note),
        )
        sale_id = cur.lastrowid
        return dict(conn.execute(
            """SELECT sh.*, i.name AS item_name FROM sales_history sh
               JOIN items i ON i.id=sh.item_id WHERE sh.id=?""",
            (sale_id,),
        ).fetchone())


def recent_crafts(limit: int = 50):
    with connection() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT ch.*, i.name AS item_name,
                      COALESCE((SELECT SUM(sh.quantity) FROM sales_history sh WHERE sh.craft_id=ch.id), 0) AS sold_quantity
               FROM craft_history ch JOIN items i ON i.id=ch.item_id
               ORDER BY ch.crafted_at DESC LIMIT ?""", (limit,)
        )]


def recent_sales(limit: int = 50):
    with connection() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT sh.*, i.name AS item_name
               FROM sales_history sh JOIN items i ON i.id=sh.item_id
               ORDER BY sh.sold_at DESC LIMIT ?""", (limit,)
        )]


def dashboard(days: int = 30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connection() as conn:
        craft = conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q, COUNT(*) c FROM craft_history WHERE crafted_at>=?", (since,)
        ).fetchone()
        sales = conn.execute(
            """SELECT COALESCE(SUM(quantity),0) q, COUNT(*) c, COALESCE(SUM(realized_profit),0) profit
               FROM sales_history WHERE sold_at>=?""", (since,)
        ).fetchone()
        top = [dict(r) for r in conn.execute(
            """SELECT i.id, i.name,
                      SUM(sh.quantity) sold_quantity,
                      SUM(sh.realized_profit) realized_profit
               FROM sales_history sh JOIN items i ON i.id=sh.item_id
               WHERE sh.sold_at>=?
               GROUP BY i.id, i.name
               ORDER BY realized_profit DESC LIMIT 5""", (since,)
        )]
        price_points = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    crafted_qty = float(craft["q"] or 0)
    sold_qty = float(sales["q"] or 0)
    return {
        "days": days,
        "crafted_quantity": crafted_qty,
        "sold_quantity": sold_qty,
        "sell_through_rate": round((sold_qty / crafted_qty * 100), 2) if crafted_qty else 0,
        "realized_profit": round(float(sales["profit"] or 0), 2),
        "price_points": price_points,
        "top_items": top,
    }
