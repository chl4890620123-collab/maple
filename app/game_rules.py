from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path


STANDARD_AUCTION_FEE_RATE = 0.05
PC_ROOM_AUCTION_FEE_RATE = 0.03
ALLOWED_AUCTION_FEE_RATES = (STANDARD_AUCTION_FEE_RATE, PC_ROOM_AUCTION_FEE_RATE)
GUILD_SHOP_DISCOUNT_RATE = 0.04
PC_ROOM_CRAFT_SUCCESS_BONUS_MAX = 0.10
DEFAULT_GUILD_DISCOUNT_ENABLED = True

_GUILD_SHOP_DISCOUNT_RATE_CONTEXT: ContextVar[float] = ContextVar(
    "maple_guild_shop_discount_rate",
    default=GUILD_SHOP_DISCOUNT_RATE,
)

FIXED_SHOP_PATH = Path(__file__).resolve().parent.parent / "data" / "fixed_shop_prices.json"


@lru_cache(maxsize=1)
def fixed_shop_catalog() -> dict:
    if not FIXED_SHOP_PATH.exists():
        return {"schema_version": 1, "items": []}
    return json.loads(FIXED_SHOP_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def fixed_shop_index() -> dict[str, dict]:
    return {
        item["item_name"]: item
        for item in fixed_shop_catalog().get("items", [])
        if item.get("item_name") and int(item.get("base_price", 0)) >= 0
    }


def fixed_shop_item(item_name: str) -> dict | None:
    return fixed_shop_index().get(item_name)


def validate_guild_shop_discount_rate(value: float) -> float:
    value = float(value)
    if value < 0.0 or value > 1.0:
        raise ValueError("길드 상점 할인율은 0% 이상 100% 이하여야 합니다.")
    return value


def current_guild_shop_discount_rate() -> float:
    return validate_guild_shop_discount_rate(_GUILD_SHOP_DISCOUNT_RATE_CONTEXT.get())


def set_guild_shop_discount_rate(value: float):
    return _GUILD_SHOP_DISCOUNT_RATE_CONTEXT.set(validate_guild_shop_discount_rate(value))


def reset_guild_shop_discount_rate(token) -> None:
    _GUILD_SHOP_DISCOUNT_RATE_CONTEXT.reset(token)


def shop_purchase_price(item_name: str, guild_discount: bool = DEFAULT_GUILD_DISCOUNT_ENABLED) -> dict | None:
    item = fixed_shop_item(item_name)
    if item is None:
        return None

    base_price = int(item["base_price"])
    eligible = bool(item.get("guild_discount_eligible", False))
    apply_discount = bool(guild_discount and eligible)
    discount_rate = current_guild_shop_discount_rate() if apply_discount else 0.0
    effective_price = int(base_price * (1 - discount_rate)) if apply_discount else base_price
    return {
        "item_name": item_name,
        "base_price": base_price,
        "effective_price": effective_price,
        "guild_discount_eligible": eligible,
        "guild_discount_applied": apply_discount,
        "guild_discount_rate": discount_rate,
        "vendor": item.get("vendor", "마이스터빌 재료 상인"),
        "source_label": item.get("source_label"),
        "source_url": item.get("source_url"),
    }


def validate_auction_fee_rate(value: float) -> float:
    value = float(value)
    if not any(abs(value - allowed) < 1e-9 for allowed in ALLOWED_AUCTION_FEE_RATES):
        allowed = ", ".join(f"{int(rate * 100)}%" for rate in ALLOWED_AUCTION_FEE_RATES)
        raise ValueError(f"판매 수수료는 고정 규칙({allowed}) 중 하나여야 합니다.")
    return value


def public_rules() -> dict:
    return {
        "auction_fee_rates": {
            "standard": STANDARD_AUCTION_FEE_RATE,
            "pc_room_receive": PC_ROOM_AUCTION_FEE_RATE,
        },
        "guild_shop_discount_rate": GUILD_SHOP_DISCOUNT_RATE,
        "default_guild_discount_enabled": DEFAULT_GUILD_DISCOUNT_ENABLED,
        "pc_room_craft_success_bonus_max": PC_ROOM_CRAFT_SUCCESS_BONUS_MAX,
        "fixed_shop_item_count": len(fixed_shop_index()),
        "pc_room_success_note": "PC방 제작 성공률 보너스는 최대치만 고정 규칙으로 보관하며, 레시피별 기본 제작 성공률이 검증된 항목에만 계산 적용합니다.",
    }
