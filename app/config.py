import os

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()
DB_PATH = os.getenv("DB_PATH", "/app/data/maple_craft.db")
DB_HOST = os.getenv("DB_HOST", "maple-db")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "maple_craft")
DB_USER = os.getenv("DB_USER", "maple_app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
DEFAULT_FEE_RATE = float(os.getenv("DEFAULT_FEE_RATE", "0.05"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
