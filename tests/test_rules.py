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


def test_game_rule_defaults_remain_stable():
    assert game_rules.STANDARD_AUCTION_FEE_RATE == 0.05
    assert game_rules.PC_ROOM_AUCTION_FEE_RATE == 0.03
    assert game_rules.GUILD_SHOP_DISCOUNT_RATE == 0.04
    assert game_rules.PC_ROOM_CRAFT_SUCCESS_BONUS_MAX == 0.10


def test_guild_discount_rate_is_request_scoped_and_validated():
    assert game_rules.current_guild_shop_discount_rate() == 0.04
    token = game_rules.set_guild_shop_discount_rate(0.07)
    try:
        discounted = game_rules.shop_purchase_price("중급 연마제", True)
        assert discounted is not None
        assert discounted["effective_price"] == 4650
        assert discounted["guild_discount_rate"] == 0.07
    finally:
        game_rules.reset_guild_shop_discount_rate(token)

    assert game_rules.current_guild_shop_discount_rate() == 0.04
    with pytest.raises(ValueError):
        game_rules.validate_guild_shop_discount_rate(-0.01)
    with pytest.raises(ValueError):
        game_rules.validate_guild_shop_discount_rate(1.01)
