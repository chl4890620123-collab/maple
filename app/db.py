import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CompatRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class MariaCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def fetchone(self):
        row = self._cursor.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self):
        return [CompatRow(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield CompatRow(row)


class MariaConnection:
    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params=()):
        cursor = self._conn.cursor()
        cursor.execute(self._sql(sql), params or ())
        return MariaCursor(cursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def ensure_parent() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection():
    if config.DB_ENGINE == "sqlite":
        ensure_parent()
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    elif config.DB_ENGINE == "mariadb":
        if not config.DB_PASSWORD:
            raise RuntimeError("DB_PASSWORD is required when DB_ENGINE=mariadb")
        import pymysql

        raw = pymysql.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
        )
        conn = MariaConnection(raw)
    else:
        raise RuntimeError(f"Unsupported DB_ENGINE: {config.DB_ENGINE}")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_sqlite(conn) -> None:
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


def _init_mariadb(conn) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS materials (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            current_price BIGINT UNSIGNED NOT NULL DEFAULT 0,
            active TINYINT(1) NOT NULL DEFAULT 1,
            source_note TEXT NULL,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS items (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            profession VARCHAR(120) NOT NULL,
            required_rank VARCHAR(120) NULL,
            output_quantity DOUBLE NOT NULL DEFAULT 1,
            current_sale_price BIGINT UNSIGNED NOT NULL DEFAULT 0,
            extra_cost BIGINT UNSIGNED NOT NULL DEFAULT 0,
            craftable TINYINT(1) NOT NULL DEFAULT 1,
            active TINYINT(1) NOT NULL DEFAULT 1,
            verification_status VARCHAR(32) NOT NULL DEFAULT 'verified',
            source_note TEXT NULL,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS recipe_components (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            item_id BIGINT UNSIGNED NOT NULL,
            material_id BIGINT UNSIGNED NOT NULL,
            quantity DOUBLE NOT NULL,
            UNIQUE KEY uq_recipe_item_material (item_id, material_id),
            CONSTRAINT fk_recipe_item FOREIGN KEY (item_id) REFERENCES items(id),
            CONSTRAINT fk_recipe_material FOREIGN KEY (material_id) REFERENCES materials(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            entity_type VARCHAR(16) NOT NULL,
            entity_id BIGINT UNSIGNED NOT NULL,
            price BIGINT UNSIGNED NOT NULL,
            recorded_at VARCHAR(40) NOT NULL,
            KEY idx_price_history_lookup (entity_type, entity_id, recorded_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS craft_history (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            item_id BIGINT UNSIGNED NOT NULL,
            quantity DOUBLE NOT NULL,
            unit_cost_snapshot DOUBLE NOT NULL,
            sale_price_snapshot DOUBLE NOT NULL,
            expected_profit_snapshot DOUBLE NOT NULL,
            fee_rate_snapshot DOUBLE NOT NULL,
            crafted_at VARCHAR(40) NOT NULL,
            note TEXT NULL,
            CONSTRAINT fk_craft_item FOREIGN KEY (item_id) REFERENCES items(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS sales_history (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            craft_id BIGINT UNSIGNED NULL,
            item_id BIGINT UNSIGNED NOT NULL,
            quantity DOUBLE NOT NULL,
            unit_sale_price DOUBLE NOT NULL,
            unit_cost_snapshot DOUBLE NOT NULL,
            fee_rate DOUBLE NOT NULL,
            realized_profit DOUBLE NOT NULL,
            sold_at VARCHAR(40) NOT NULL,
            note TEXT NULL,
            CONSTRAINT fk_sale_craft FOREIGN KEY (craft_id) REFERENCES craft_history(id),
            CONSTRAINT fk_sale_item FOREIGN KEY (item_id) REFERENCES items(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            `key` VARCHAR(190) NOT NULL PRIMARY KEY,
            `value` TEXT NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ]
    for statement in statements:
        conn.execute(statement)


def init_db() -> None:
    with connection() as conn:
        if config.DB_ENGINE == "mariadb":
            _init_mariadb(conn)
        else:
            _init_sqlite(conn)
        seed_if_empty(conn)


def seed_if_empty(conn) -> None:
    count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    if count:
        return

    seed_path = Path(__file__).resolve().parent.parent / "data" / "seed.json"
    if not seed_path.exists():
        return

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    ts = now_iso()

    for material in seed.get("materials", []):
        cur = conn.execute(
            """INSERT INTO materials(name, current_price, source_note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (material["name"], int(material.get("price", 0)), material.get("source_note"), ts, ts),
        )
        material_id = cur.lastrowid
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('material', ?, ?, ?)",
            (material_id, int(material.get("price", 0)), ts),
        )

    material_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM materials")}

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
        item_id = cur.lastrowid
        conn.execute(
            "INSERT INTO price_history(entity_type, entity_id, price, recorded_at) VALUES ('item', ?, ?, ?)",
            (item_id, int(item.get("sale_price", 0)), ts),
        )
        for component in item.get("recipe", []):
            material_id = material_ids.get(component["material"])
            if material_id is None:
                raise ValueError(f"Unknown material in seed: {component['material']}")
            conn.execute(
                "INSERT INTO recipe_components(item_id, material_id, quantity) VALUES (?, ?, ?)",
                (item_id, material_id, float(component["quantity"])),
            )
