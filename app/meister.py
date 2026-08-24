from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import config
from .db import connection, now_iso


CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "meister_catalog.json"
CATEGORY_ORDER = ("herbalism", "mining", "equipment", "accessory", "alchemy")
ROLE_LABELS = {"input": "재료", "output": "결과물"}


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        raise RuntimeError("마이스터빌 카탈로그가 없습니다. catalog sync를 먼저 실행하세요.")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    categories = data.get("categories", [])
    actual = {category.get("key") for category in categories}
    expected = set(CATEGORY_ORDER)
    if actual != expected:
        raise RuntimeError(f"마이스터빌 카테고리 불일치: {sorted(actual)}")
    return data


def catalog_meta() -> dict:
    catalog = load_catalog()
    return {
        "schema_version": catalog.get("schema_version"),
        "synced_at": catalog.get("synced_at"),
        "total_recipe_count": catalog.get("total_recipe_count", 0),
        "source_policy": catalog.get("source_policy", {}),
        "categories": [
            {
                "key": category["key"],
                "name": category["name"],
                "recipe_count": len(category.get("recipes", [])),
                "source_url": category.get("source_url"),
            }
            for category in catalog["categories"]
        ],
    }


def categories() -> list[dict]:
    by_key = {item["key"]: item for item in catalog_meta()["categories"]}
    return [by_key[key] for key in CATEGORY_ORDER]


def _all_recipes(category_key: str | None = None) -> list[dict]:
    recipes: list[dict] = []
    for category in load_catalog()["categories"]:
        if category_key and category["key"] != category_key:
            continue
        recipes.extend(category.get("recipes", []))
    return recipes


def catalog_item_index(category_key: str | None = None) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for recipe in _all_recipes(category_key):
        for role, entries in (("input", recipe.get("inputs", [])), ("output", recipe.get("outputs", []))):
            for entry in entries:
                name = entry["name"].strip()
                item = index.setdefault(name, {"roles": set(), "categories": set()})
                item["roles"].add(role)
                item["categories"].add(recipe["category_key"])
    return index


def _create_market_tables(conn) -> None:
    if config.DB_ENGINE == "mariadb":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_prices (
                item_name VARCHAR(255) NOT NULL PRIMARY KEY,
                current_price BIGINT UNSIGNED NOT NULL DEFAULT 0,
                source VARCHAR(64) NOT NULL DEFAULT 'catalog_unpriced',
                updated_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_price_history (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                item_name VARCHAR(255) NOT NULL,
                price BIGINT UNSIGNED NOT NULL,
                source VARCHAR(64) NOT NULL,
                recorded_at VARCHAR(40) NOT NULL,
                KEY idx_market_price_history (item_name, recorded_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_prices (
                item_name TEXT PRIMARY KEY,
                current_price INTEGER NOT NULL DEFAULT 0 CHECK(current_price >= 0),
                source TEXT NOT NULL DEFAULT 'catalog_unpriced',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL CHECK(price >= 0),
                source TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_price_history ON market_price_history(item_name, recorded_at)"
        )


def _insert_market_if_missing(conn, item_name: str, price: int, source: str, updated_at: str) -> None:
    existing = conn.execute("SELECT item_name FROM market_prices WHERE item_name = ?", (item_name,)).fetchone()
    if existing is not None:
        return
    conn.execute(
        "INSERT INTO market_prices(item_name, current_price, source, updated_at) VALUES (?, ?, ?, ?)",
        (item_name, int(price), source, updated_at),
    )


def _migrate_legacy_prices(conn) -> None:
    candidates: dict[str, dict] = {}
    for row in conn.execute("SELECT name, current_price, updated_at FROM materials").fetchall():
        if int(row["current_price"] or 0) <= 0:
            continue
        candidates[row["name"]] = {
            "price": int(row["current_price"]),
            "source": "legacy_material",
            "updated_at": row["updated_at"],
        }

    for row in conn.execute("SELECT name, current_sale_price, updated_at FROM items").fetchall():
        if int(row["current_sale_price"] or 0) <= 0:
            continue
        candidate = {
            "price": int(row["current_sale_price"]),
            "source": "legacy_item",
            "updated_at": row["updated_at"],
        }
        previous = candidates.get(row["name"])
        if previous is None or (candidate["updated_at"] or "") > (previous["updated_at"] or ""):
            candidates[row["name"]] = candidate

    for name, value in candidates.items():
        _insert_market_if_missing(conn, name, value["price"], value["source"], value["updated_at"] or now_iso())


def _ensure_catalog_market_rows(conn) -> None:
    ts = now_iso()
    for item_name in catalog_item_index():
        _insert_market_if_missing(conn, item_name, 0, "catalog_unpriced", ts)


def init_market_prices() -> None:
    with connection() as conn:
        _create_market_tables(conn)
        _migrate_legacy_prices(conn)
        _ensure_catalog_market_rows(conn)


def _price_rows(conn) -> dict[str, dict]:
    return {
        row["item_name"]: {
            "item_name": row["item_name"],
            "current_price": int(row["current_price"]),
            "source": row["source"],
            "updated_at": row["updated_at"],
            "price_known": row["source"] != "catalog_unpriced",
        }
        for row in conn.execute(
            "SELECT item_name, current_price, source, updated_at FROM market_prices"
        ).fetchall()
    }


def list_market_prices(category_key: str | None = None, q: str | None = None) -> list[dict]:
    item_index = catalog_item_index(category_key)
    needle = (q or "").strip().casefold()
    with connection() as conn:
        prices = _price_rows(conn)

    rows = []
    for name, metadata in item_index.items():
        if needle and needle not in name.casefold():
            continue
        price = prices.get(name, {"current_price": 0, "source": "catalog_unpriced", "updated_at": None, "price_known": False})
        rows.append(
            {
                "item_name": name,
                "current_price": price["current_price"],
                "price_known": price["price_known"],
                "source": price["source"],
                "updated_at": price["updated_at"],
                "roles": sorted(metadata["roles"]),
                "role_labels": [ROLE_LABELS[role] for role in sorted(metadata["roles"])],
                "categories": sorted(metadata["categories"], key=lambda key: CATEGORY_ORDER.index(key)),
            }
        )
    rows.sort(key=lambda row: (not row["price_known"], row["item_name"]))
    return rows


def bulk_update_market_prices(entries: list[dict]) -> list[dict]:
    allowed = set(catalog_item_index())
    unknown = sorted({entry["item_name"] for entry in entries if entry["item_name"] not in allowed})
    if unknown:
        raise ValueError(f"카탈로그에 없는 아이템입니다: {', '.join(unknown[:5])}")

    deduped: dict[str, int] = {}
    for entry in entries:
        deduped[entry["item_name"]] = int(entry["price"])

    ts = now_iso()
    with connection() as conn:
        _create_market_tables(conn)
        for item_name, price in deduped.items():
            existing = conn.execute("SELECT item_name FROM market_prices WHERE item_name = ?", (item_name,)).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO market_prices(item_name, current_price, source, updated_at) VALUES (?, ?, 'manual', ?)",
                    (item_name, price, ts),
                )
            else:
                conn.execute(
                    "UPDATE market_prices SET current_price = ?, source = 'manual', updated_at = ? WHERE item_name = ?",
                    (price, ts, item_name),
                )
            conn.execute(
                "INSERT INTO market_price_history(item_name, price, source, recorded_at) VALUES (?, ?, 'manual', ?)",
                (item_name, price, ts),
            )

    updated = []
    with connection() as conn:
        prices = _price_rows(conn)
        for item_name in deduped:
            updated.append(prices[item_name])
    return updated


def _price_record(prices: dict[str, dict], item_name: str) -> tuple[int, bool, str]:
    row = prices.get(item_name)
    if row is None:
        return 0, False, "catalog_unpriced"
    return int(row["current_price"]), bool(row["price_known"]), row["source"]


def calculate_recipe(recipe: dict, prices: dict[str, dict], fee_rate: float) -> dict:
    missing: list[str] = []
    input_rows = []
    output_rows = []
    input_cost_value = 0.0
    gross_value = 0.0
    inputs_complete = True
    outputs_complete = True

    for entry in recipe.get("inputs", []):
        price, known, source = _price_record(prices, entry["name"])
        quantity = float(entry.get("quantity", 1))
        if not known:
            inputs_complete = False
            missing.append(entry["name"])
        cost = price * quantity
        input_cost_value += cost
        input_rows.append(
            {
                "item_name": entry["name"],
                "quantity": quantity,
                "current_price": price,
                "price_known": known,
                "source": source,
                "cost": cost if known else None,
            }
        )

    for entry in recipe.get("outputs", []):
        price, known, source = _price_record(prices, entry["name"])
        quantity = float(entry.get("quantity", 1))
        probability = float(entry.get("probability", 100))
        expected_quantity = quantity * probability / 100.0
        if not known:
            outputs_complete = False
            missing.append(entry["name"])
        expected_gross = price * expected_quantity
        gross_value += expected_gross
        output_rows.append(
            {
                "item_name": entry["name"],
                "quantity": quantity,
                "probability": probability,
                "expected_quantity": expected_quantity,
                "current_price": price,
                "price_known": known,
                "source": source,
                "expected_gross": expected_gross if known else None,
            }
        )

    complete = inputs_complete and outputs_complete
    input_cost = input_cost_value if inputs_complete else None
    gross_expected = gross_value if outputs_complete else None
    net_expected = gross_value * (1 - fee_rate) if outputs_complete else None
    profit = net_expected - input_cost_value if complete else None
    margin = (profit / input_cost_value * 100) if complete and input_cost_value > 0 else None

    return {
        "recipe_key": recipe["recipe_key"],
        "name": recipe["name"],
        "category_key": recipe["category_key"],
        "profession": recipe["profession"],
        "required_level": recipe.get("required_level"),
        "verification_status": recipe.get("verification_status", "third_party_baseline"),
        "source_url": recipe.get("source_url"),
        "inputs": input_rows,
        "outputs": output_rows,
        "input_cost": input_cost,
        "gross_expected": gross_expected,
        "net_expected": net_expected,
        "expected_profit": profit,
        "margin_rate": margin,
        "price_complete": complete,
        "missing_prices": sorted(set(missing)),
    }


def calculations(fee_rate: float, category_key: str | None = None, q: str | None = None) -> list[dict]:
    if category_key and category_key not in CATEGORY_ORDER:
        raise ValueError("알 수 없는 마이스터빌 카테고리입니다.")
    needle = (q or "").strip().casefold()
    with connection() as conn:
        prices = _price_rows(conn)

    rows = []
    for recipe in _all_recipes(category_key):
        if needle and needle not in recipe["name"].casefold():
            continue
        rows.append(calculate_recipe(recipe, prices, fee_rate))

    rows.sort(
        key=lambda row: (
            not row["price_complete"],
            -(row["expected_profit"] if row["expected_profit"] is not None else float("-inf")),
            row["name"],
        )
    )
    return rows
