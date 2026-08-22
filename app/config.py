import os

DB_PATH = os.getenv("DB_PATH", "/app/data/maple_craft.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
DEFAULT_FEE_RATE = float(os.getenv("DEFAULT_FEE_RATE", "0.05"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
