from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import config, game_rules
from .db import connection, now_iso


CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "meister_catalog.json"
OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "meister_overrides.json"
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
    # sync_meister_catalog.py applies meister_overrides.json before writing the
    # tracked snapshot. Runtime reapplication would duplicate future "add"
    # overrides and make production differ from the reviewed catalog file.
    return data


def _apply_overrides(catalog: dict) -> dict:
    if not OVERRIDES_PATH.exists():
        return catalog
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    disabled = set(overrides.get("disable", []))
    replacements = {item["recipe_key"]: item for item in overrides.get("replace", []) if item.get("recipe_key")}
    additions = overrides.get("add", [])

    for category in catalog.get("categories", []):
        merged = []
        for recipe in category.get("recipes", []):
            key = recipe.get("recipe_key")
            if key in disabled:
                continue
            if key in replacements:
                replacement = {**recipe, **replacements[key]}
                merged.append(replacement)
            else:
                merged.append(recipe)
        category["recipes"] = merged
        category["recipe_count"] = len(merged)

    by_category = {item["key"]: item for item in catalog.get("categories", [])}
    for recipe in additions:
        key = recipe.get("category_key")
        if key not in by_category:
            continue
        by_category[key]["recipes"].append(recipe)
        by_category[key]["recipe_count"] = len(by_category[key]["recipes"])

    catalog["total_recipe_count"] = sum(len(category.get("recipes", [])) for category in catalog.get("categories", []))
    return catalog


def catalog_meta() -> dict:
    catalog = load_catalog()
    return {
        "schema_version": catalog.get("schema_version"),
        "synced_at": catalog.get("synced_at"),
        "total_recipe_count": catalog.get("total_recipe_count", 0),
        "source_policy": catalog.get("source_policy", {}),
        "rules": game_rules.public_rules(),
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


def fixed_shop_items() -> list[dict]:
    rows = []
    for item in game_rules.fixed_shop_catalog().get("items", []):
        with_discount = game_rules.shop_purchase_price(item["item_name"], True)
        without_discount = game_rules.shop_purchase_price(item["item_name"], False)
        rows.append(
            {
                **item,
                "guild_price": with_discount["effective_price"] if with_discount else item["base_price"],
                "regular_price": without_discount["effective_price"] if without_discount else item["base_price"],
            }
        )
    rows.sort(key=lambda row: row["item_name"])
    return rows


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
                source TEXT NOT NULL DEFAULT 'catalog_unpriced',
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
        if game_rules.fixed_shop_item(name):
            continue
        _insert_market_if_missing(conn, name, value["price"], value["source"], value["updated_at"] or now_iso())


def _ensure_catalog_market_rows(conn) -> None:
    ts = now_iso()
    for item_name in catalog_item_index():
        if game_rules.fixed_shop_item(item_name):
            continue
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
        if game_rules.fixed_shop_item(name):
            continue
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
                "price_locked": False,
            }
        )
    rows.sort(key=lambda row: (not row["price_known"], row["item_name"]))
    return rows


def bulk_update_market_prices(entries: list[dict]) -> list[dict]:
    catalog_names = set(catalog_item_index())
    fixed_names = set(game_rules.fixed_shop_index())
    allowed = catalog_names - fixed_names
    unknown = sorted({entry["item_name"] for entry in entries if entry["item_name"] not in allowed})
    if unknown:
        raise ValueError(f"변동 시세로 수정할 수 없는 아이템입니다: {', '.join(unknown[:5])}")

    deduped: dict[str, int] = {}
    for entry in entries:
        price = int(entry["price"])
        if price < 0:
            raise ValueError("시세는 0 이상이어야 합니다.")
        deduped[entry["item_name"]] = price

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

    with connection() as conn:
        prices = _price_rows(conn)
        return [prices[item_name] for item_name in deduped]


def _market_price_record(prices: dict[str, dict], item_name: str) -> tuple[int, bool, str]:
    row = prices.get(item_name)
    if row is None:
        return 0, False, "catalog_unpriced"
    return int(row["current_price"]), bool(row["price_known"]), row["source"]


def calculate_recipe(
    recipe: dict,
    prices: dict[str, dict],
    fee_rate: float,
    guild_discount: bool = game_rules.DEFAULT_GUILD_DISCOUNT_ENABLED,
) -> dict:
    fee_rate = game_rules.validate_auction_fee_rate(fee_rate)
    missing: list[str] = []
    input_rows = []
    output_rows = []
    input_cost_value = 0.0
    gross_value = 0.0
    inputs_complete = True
    outputs_complete = True

    for entry in recipe.get("inputs", []):
        item_name = entry["name"]
        quantity = float(entry.get("quantity", 1))
        shop = game_rules.shop_purchase_price(item_name, guild_discount)
        if shop is not None:
            price = int(shop["effective_price"])
            known = True
            source = "fixed_shop"
            fixed = True
        else:
            price, known, source = _market_price_record(prices, item_name)
            fixed = False

        if not known:
            inputs_complete = False
            missing.append(item_name)
        cost = price * quantity
        input_cost_value += cost
        input_rows.append(
            {
                "item_name": item_name,
                "quantity": quantity,
                "current_price": price,
                "price_known": known,
                "source": source,
                "fixed_shop": fixed,
                "shop_base_price": shop["base_price"] if shop else None,
                "guild_discount_applied": shop["guild_discount_applied"] if shop else False,
                "cost": cost if known else None,
            }
        )

    for entry in recipe.get("outputs", []):
        price, known, source = _market_price_record(prices, entry["name"])
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
        "fee_rate": fee_rate,
        "guild_discount_enabled": bool(guild_discount),
        "guild_shop_discount_rate": game_rules.GUILD_SHOP_DISCOUNT_RATE,
    }


def calculations(
    fee_rate: float,
    category_key: str | None = None,
    q: str | None = None,
    guild_discount: bool = game_rules.DEFAULT_GUILD_DISCOUNT_ENABLED,
) -> list[dict]:
    game_rules.validate_auction_fee_rate(fee_rate)
    if category_key and category_key not in CATEGORY_ORDER:
        raise ValueError("알 수 없는 마이스터빌 카테고리입니다.")
    needle = (q or "").strip().casefold()
    with connection() as conn:
        prices = _price_rows(conn)

    rows = []
    for recipe in _all_recipes(category_key):
        if needle and needle not in recipe["name"].casefold():
            continue
        rows.append(calculate_recipe(recipe, prices, fee_rate, guild_discount))

    rows.sort(
        key=lambda row: (
            not row["price_complete"],
            -(row["expected_profit"] if row["expected_profit"] is not None else float("-inf")),
            row["name"],
        )
    )
    return rows
