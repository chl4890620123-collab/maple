from typing import Literal

from pydantic import BaseModel, Field


AuctionFeeRate = Literal[0.05, 0.03]


class PriceUpdate(BaseModel):
    price: int = Field(ge=0)


class MarketPriceEntry(BaseModel):
    item_name: str = Field(min_length=1, max_length=255)
    price: int = Field(ge=0)


class MarketPriceBulkUpdate(BaseModel):
    prices: list[MarketPriceEntry] = Field(min_length=1, max_length=500)


class CraftCreate(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    fee_rate: AuctionFeeRate = 0.05
    note: str | None = None


class SaleCreate(BaseModel):
    craft_id: int | None = None
    item_id: int
    quantity: float = Field(gt=0)
    unit_sale_price: float = Field(ge=0)
    fee_rate: AuctionFeeRate = 0.05
    note: str | None = None
