from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import service
from .config import ADMIN_TOKEN, CORS_ORIGINS, DEFAULT_FEE_RATE
from .db import init_db
from .schemas import CraftCreate, PriceUpdate, SaleCreate

app = FastAPI(title="Maple Craft Analytics", version="0.1.0")

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


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다.")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def public_config():
    return {
        "default_fee_rate": DEFAULT_FEE_RATE,
        "write_protected": bool(ADMIN_TOKEN),
    }


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
def get_calculations(fee_rate: float = Query(default=DEFAULT_FEE_RATE, ge=0, le=0.2)):
    return service.calculations(fee_rate)


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
