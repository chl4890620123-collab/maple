from typing import Literal

from pydantic import BaseModel, Field


AuctionFeeRate = Literal[0.05, 0.03]
RecipeAccessType = Literal["unknown", "permanent", "daily", "one_time"]


class PriceUpdate(BaseModel):
    price: int = Field(ge=0)


class MarketPriceEntry(BaseModel):
    item_name: str = Field(min_length=1, max_length=255)
    price: int = Field(ge=0)


class MarketPriceBulkUpdate(BaseModel):
    prices: list[MarketPriceEntry] = Field(min_length=1, max_length=500)


class RecipeStateUpdate(BaseModel):
    access_type: RecipeAccessType
    is_owned: bool = False


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


class MeisterCraftCreate(BaseModel):
    recipe_key: str = Field(min_length=1, max_length=255)
    quantity: float = Field(gt=0, le=100000)
    fee_rate: AuctionFeeRate = 0.05
    guild_discount: bool = True
    guild_discount_rate: float = Field(default=0.04, ge=0, le=1)
    rank_position: int | None = Field(default=None, ge=1, le=100000)
    note: str | None = Field(default=None, max_length=1000)


class MeisterSaleCreate(BaseModel):
    gross_sale_amount: float = Field(ge=0)
    fee_rate: AuctionFeeRate = 0.05
    note: str | None = Field(default=None, max_length=1000)
