import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_parent() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection():
    ensure_parent()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                current_price INTEGER NOT NULL DEFAULT 0 CHECK(current_price >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                source_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                profession TEXT NOT NULL,
                required_rank TEXT,
                output_quantity REAL NOT NULL DEFAULT 1 CHECK(output_quantity > 0),
                current_sale_price INTEGER NOT NULL DEFAULT 0 CHECK(current_sale_price >= 0),
                extra_cost INTEGER NOT NULL DEFAULT 0 CHECK(extra_cost >= 0),
                craftable INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                verification_status TEXT NOT NULL DEFAULT 'verified',
                source_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recipe_components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                material_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                UNIQUE(item_id, material_id),
                FOREIGN KEY(item_id) REFERENCES items(id),
                FOREIGN KEY(material_id) REFERENCES materials(id)
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('material', 'item')),
                entity_id INTEGER NOT NULL,
                price INTEGER NOT NULL CHECK(price >= 0),
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_history_lookup
                ON price_history(entity_type, entity_id, recorded_at);

            CREATE TABLE IF NOT EXISTS craft_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_cost_snapshot REAL NOT NULL,
                sale_price_snapshot REAL NOT NULL,
                expected_profit_snapshot REAL NOT NULL,
                fee_rate_snapshot REAL NOT NULL,
                crafted_at TEXT NOT NULL,
                note TEXT,
                FOREIGN KEY(item_id) REFERENCES items(id)
            );

            CREATE TABLE IF NOT EXISTS sales_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                craft_id INTEGER,
                item_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_sale_price REAL NOT NULL CHECK(unit_sale_price >= 0),
                unit_cost_snapshot REAL NOT NULL,
                fee_rate REAL NOT NULL,
                realized_profit REAL NOT NULL,
                sold_at TEXT NOT NULL,
                note TEXT,
                FOREIGN KEY(craft_id) REFERENCES craft_history(id),
                FOREIGN KEY(item_id) REFERENCES items(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        seed_if_empty(conn)


def seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    if count:
        return

    seed_path = Path(__file__).resolve().parent.parent / "data" / "seed.json"
    if not seed_path.exists():
        return

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    ts = now_iso()

    for m in seed.get("materials", []):
        cur = conn.execute(
            """INSERT INTO materials(name, current_price, source_note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (m["name"], int(m.get("price", 0)), m.get("source_note"), ts, ts),
        )
        mid = cur.lastrowid
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('material', ?, ?, ?)",
            (mid, int(m.get("price", 0)), ts),
        )

    material_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM materials")}

    for item in seed.get("items", []):
        cur = conn.execute(
            """INSERT INTO items(
                   name, profession, required_rank, output_quantity, current_sale_price,
                   extra_cost, craftable, verification_status, source_note, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["name"],
                item.get("profession", "기타"),
                item.get("required_rank"),
                float(item.get("output_quantity", 1)),
                int(item.get("sale_price", 0)),
                int(item.get("extra_cost", 0)),
                1 if item.get("craftable", True) else 0,
                item.get("verification_status", "verified"),
                item.get("source_note"),
                ts,
                ts,
            ),
        )
        iid = cur.lastrowid
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('item', ?, ?, ?)",
            (iid, int(item.get("sale_price", 0)), ts),
        )
        for component in item.get("recipe", []):
            mid = material_ids.get(component["material"])
            if mid is None:
                raise ValueError(f"Unknown material in seed: {component['material']}")
            conn.execute(
                "INSERT INTO recipe_components(item_id, material_id, quantity) VALUES (?, ?, ?)",
                (iid, mid, float(component["quantity"])),
            )
