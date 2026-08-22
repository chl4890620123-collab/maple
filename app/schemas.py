from pydantic import BaseModel, Field


class PriceUpdate(BaseModel):
    price: int = Field(ge=0)


class CraftCreate(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    fee_rate: float = Field(ge=0, le=0.2)
    note: str | None = None


class SaleCreate(BaseModel):
    craft_id: int | None = None
    item_id: int
    quantity: float = Field(gt=0)
    unit_sale_price: float = Field(ge=0)
    fee_rate: float = Field(ge=0, le=0.2)
    note: str | None = None
