from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import game_rules, meister, service
from .config import ADMIN_TOKEN, CORS_ORIGINS, DEFAULT_FEE_RATE
from .db import init_db
from .schemas import CraftCreate, MarketPriceBulkUpdate, PriceUpdate, SaleCreate

app = FastAPI(title="Maple Craft Analytics", version="0.4.0")

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )


@app.on_event("startup")
def startup() -> None:
    init_db()
    meister.init_market_prices()


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다.")


def recipe_metadata_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for category in meister.load_catalog().get("categories", []):
        for recipe in category.get("recipes", []):
            index[recipe["recipe_key"]] = {
                "item_level": recipe.get("item_level"),
                "source_label": recipe.get("source_label", "메이플스토리 인벤 제작 DB"),
            }
    return index


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def public_config():
    return {
        "default_fee_rate": DEFAULT_FEE_RATE,
        "write_protected": bool(ADMIN_TOKEN),
        "game_rules": game_rules.public_rules(),
    }


@app.get("/api/meister/meta")
def meister_meta():
    return meister.catalog_meta()


@app.get("/api/meister/categories")
def meister_categories():
    return meister.categories()


@app.get("/api/meister/fixed-shop-prices")
def meister_fixed_shop_prices():
    return meister.fixed_shop_items()


@app.get("/api/meister/calculations")
def meister_calculations(
    fee_rate: float = Query(default=DEFAULT_FEE_RATE),
    category_key: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    guild_discount: bool = Query(default=game_rules.DEFAULT_GUILD_DISCOUNT_ENABLED),
):
    try:
        rows = meister.calculations(fee_rate, category_key, q, guild_discount)
        metadata = recipe_metadata_index()
        for row in rows:
            info = metadata.get(row["recipe_key"], {})
            row["item_level"] = info.get("item_level")
            row["source_label"] = info.get("source_label", "메이플스토리 인벤 제작 DB")
            row["input_type_count"] = len(row.get("inputs", []))
            row["input_total_quantity"] = sum(float(item.get("quantity", 0)) for item in row.get("inputs", []))
            row["output_type_count"] = len(row.get("outputs", []))
            row["output_expected_quantity"] = sum(
                float(item.get("expected_quantity", 0)) for item in row.get("outputs", [])
            )
        return rows
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/market-prices")
def market_prices(
    category_key: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
):
    if category_key and category_key not in meister.CATEGORY_ORDER:
        raise HTTPException(status_code=400, detail="알 수 없는 마이스터빌 카테고리입니다.")
    return meister.list_market_prices(category_key, q)


@app.patch("/api/market-prices/bulk", dependencies=[Depends(require_admin)])
def patch_market_prices(body: MarketPriceBulkUpdate):
    try:
        return {
            "updated": meister.bulk_update_market_prices(
                [entry.model_dump() for entry in body.prices]
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Legacy endpoints are retained for existing craft/sale history and old data.
@app.get("/api/materials")
def get_materials():
    return service.list_materials()


@app.patch("/api/materials/{material_id}/price", dependencies=[Depends(require_admin)])
def patch_material_price(material_id: int, body: PriceUpdate):
    result = service.update_material_price(material_id, body.price)
    if result is None:
        raise HTTPException(404, "재료를 찾을 수 없습니다.")
    return result


@app.patch("/api/items/{item_id}/sale-price", dependencies=[Depends(require_admin)])
def patch_item_sale_price(item_id: int, body: PriceUpdate):
    result = service.update_item_sale_price(item_id, body.price)
    if result is None:
        raise HTTPException(404, "제작품을 찾을 수 없습니다.")
    return result


@app.get("/api/calculations")
def get_calculations(fee_rate: float = Query(default=DEFAULT_FEE_RATE)):
    try:
        return service.calculations(fee_rate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/crafts", dependencies=[Depends(require_admin)])
def post_craft(body: CraftCreate):
    result = service.record_craft(body.item_id, body.quantity, body.fee_rate, body.note)
    if result is None:
        raise HTTPException(404, "제작품을 찾을 수 없습니다.")
    return result


@app.get("/api/crafts")
def get_crafts(limit: int = Query(default=50, ge=1, le=200)):
    return service.recent_crafts(limit)


@app.post("/api/sales", dependencies=[Depends(require_admin)])
def post_sale(body: SaleCreate):
    result = service.record_sale(
        body.craft_id,
        body.item_id,
        body.quantity,
        body.unit_sale_price,
        body.fee_rate,
        body.note,
    )
    if result is None:
        raise HTTPException(400, "판매 기록을 저장할 수 없습니다. 제작 기록과 아이템을 확인하세요.")
    return result


@app.get("/api/sales")
def get_sales(limit: int = Query(default=50, ge=1, le=200)):
    return service.recent_sales(limit)


@app.get("/api/dashboard")
def get_dashboard(days: int = Query(default=30, ge=1, le=3650)):
    return service.dashboard(days)


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
