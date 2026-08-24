import os
import tempfile

import pytest


def _configure_sqlite(db_path: str):
    os.environ["DB_ENGINE"] = "sqlite"
    os.environ["DB_PATH"] = db_path
    from app import config

    config.DB_ENGINE = "sqlite"
    config.DB_PATH = db_path
    from app import db, meister

    return db, meister


def test_catalog_has_all_meisterville_categories():
    from app import meister

    catalog = meister.load_catalog()
    keys = {category["key"] for category in catalog["categories"]}
    assert keys == {"herbalism", "mining", "equipment", "accessory", "alchemy"}
    assert catalog["total_recipe_count"] >= 50

    recipe_keys = []
    has_item_level = False
    for category in catalog["categories"]:
        assert len(category["recipes"]) >= 5
        for recipe in category["recipes"]:
            assert recipe["inputs"]
            assert recipe["outputs"]
            recipe_keys.append(recipe["recipe_key"])
            if recipe.get("item_level") is not None:
                assert int(recipe["item_level"]) > 0
                has_item_level = True
            for material in recipe["inputs"]:
                assert float(material.get("quantity", 0)) > 0
            for output in recipe["outputs"]:
                assert float(output.get("quantity", 0)) > 0
                assert 0 < float(output.get("probability", 100)) <= 100
    assert has_item_level, "catalog should preserve item-level metadata from the recipe source"
    assert len(recipe_keys) == len(set(recipe_keys))


def test_expected_profit_uses_output_probability():
    from app.meister import calculate_recipe

    recipe = {
        "recipe_key": "test",
        "name": "테스트 제작",
        "category_key": "alchemy",
        "profession": "연금술",
        "required_level": 1,
        "verification_status": "test",
        "inputs": [{"name": "재료A", "quantity": 1}],
        "outputs": [
            {"name": "결과X", "quantity": 1, "probability": 90},
            {"name": "결과Y", "quantity": 1, "probability": 10},
        ],
    }
    prices = {
        "재료A": {"current_price": 100, "price_known": True, "source": "manual"},
        "결과X": {"current_price": 200, "price_known": True, "source": "manual"},
        "결과Y": {"current_price": 50, "price_known": True, "source": "manual"},
    }

    result = calculate_recipe(recipe, prices, 0.05, guild_discount=False)
    assert result["price_complete"] is True
    assert result["input_cost"] == 100
    assert result["gross_expected"] == 185
    assert round(result["net_expected"], 2) == 175.75
    assert round(result["expected_profit"], 2) == 75.75


def test_missing_price_never_becomes_fake_profit():
    from app.meister import calculate_recipe

    recipe = {
        "recipe_key": "test-missing",
        "name": "테스트 제작",
        "category_key": "mining",
        "profession": "채광",
        "inputs": [{"name": "광석", "quantity": 2}],
        "outputs": [{"name": "제련물", "quantity": 1, "probability": 100}],
    }
    prices = {
        "광석": {"current_price": 100, "price_known": True, "source": "manual"},
        "제련물": {"current_price": 0, "price_known": False, "source": "catalog_unpriced"},
    }

    result = calculate_recipe(recipe, prices, 0.05)
    assert result["price_complete"] is False
    assert result["expected_profit"] is None
    assert result["missing_prices"] == ["제련물"]


def test_fixed_shop_price_uses_guild_discount():
    from app import game_rules
    from app.meister import calculate_recipe

    recipe = {
        "recipe_key": "test-shop",
        "name": "상점 테스트",
        "category_key": "accessory",
        "profession": "장신구제작",
        "inputs": [{"name": "중급 연마제", "quantity": 2}],
        "outputs": [{"name": "결과", "quantity": 1, "probability": 100}],
    }
    prices = {"결과": {"current_price": 20000, "price_known": True, "source": "manual"}}

    normal = calculate_recipe(recipe, prices, 0.05, guild_discount=False)
    guild = calculate_recipe(recipe, prices, 0.05, guild_discount=True)

    assert normal["input_cost"] == 10000
    assert guild["input_cost"] == 9600
    assert guild["inputs"][0]["source"] == "fixed_shop"
    assert guild["inputs"][0]["guild_discount_applied"] is True
    assert game_rules.GUILD_SHOP_DISCOUNT_RATE == 0.04


def test_only_fixed_auction_fees_are_allowed():
    from app.game_rules import validate_auction_fee_rate

    assert validate_auction_fee_rate(0.05) == 0.05
    assert validate_auction_fee_rate(0.03) == 0.03
    with pytest.raises(ValueError):
        validate_auction_fee_rate(0.04)


def test_market_price_is_unique_across_input_and_output_roles():
    with tempfile.TemporaryDirectory() as temp_dir:
        db, meister = _configure_sqlite(os.path.join(temp_dir, "meister.db"))
        db.init_db()
        meister.init_market_prices()
        prices = meister.list_market_prices()
        names = [row["item_name"] for row in prices]
        assert len(names) == len(set(names))
        assert any(set(row["roles"]) == {"input", "output"} for row in prices)
        assert "중급 연마제" not in names


def test_fixed_shop_endpoint_data_is_complete():
    from app import game_rules

    shop = game_rules.fixed_shop_index()
    assert shop["하급 연마제"]["base_price"] == 1000
    assert shop["중급 연마제"]["base_price"] == 5000
    assert shop["고급 연마제"]["base_price"] == 10000
    assert shop["최고급 연마제"]["base_price"] == 50000
    assert shop["최고급 허브오일병"]["base_price"] == 1000
    assert shop["최고급 포션 빈 병"]["base_price"] == 800


def test_recipe_metadata_index_keeps_source_details():
    from app.main import recipe_metadata_index

    metadata = recipe_metadata_index()
    assert metadata
    assert any(int(row.get("item_level") or 0) > 0 for row in metadata.values())
    assert all(row.get("source_label") for row in metadata.values())
