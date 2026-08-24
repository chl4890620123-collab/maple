import pytest
from pydantic import ValidationError

from app import game_rules
from app.schemas import CraftCreate, SaleCreate


def test_fixed_fee_rules_are_shared_by_legacy_payloads():
    assert CraftCreate(item_id=1, quantity=1, fee_rate=0.05).fee_rate == 0.05
    assert SaleCreate(item_id=1, quantity=1, unit_sale_price=1000, fee_rate=0.03).fee_rate == 0.03

    with pytest.raises(ValidationError):
        CraftCreate(item_id=1, quantity=1, fee_rate=0.04)
    with pytest.raises(ValidationError):
        SaleCreate(item_id=1, quantity=1, unit_sale_price=1000, fee_rate=0.04)


def test_game_rule_constants_are_not_runtime_tunable():
    assert game_rules.STANDARD_AUCTION_FEE_RATE == 0.05
    assert game_rules.PC_ROOM_AUCTION_FEE_RATE == 0.03
    assert game_rules.GUILD_SHOP_DISCOUNT_RATE == 0.04
    assert game_rules.PC_ROOM_CRAFT_SUCCESS_BONUS_MAX == 0.10
