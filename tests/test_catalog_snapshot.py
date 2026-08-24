import json


def test_runtime_catalog_matches_tracked_snapshot(monkeypatch, tmp_path):
    from app import meister

    tracked = json.loads(meister.CATALOG_PATH.read_text(encoding="utf-8"))
    snapshot_path = tmp_path / "meister_catalog.json"
    snapshot_path.write_text(json.dumps(tracked, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(meister, "CATALOG_PATH", snapshot_path)
    meister.load_catalog.cache_clear()
    try:
        loaded = meister.load_catalog()
        assert loaded == tracked
        recipe_keys = [
            recipe["recipe_key"]
            for category in loaded["categories"]
            for recipe in category.get("recipes", [])
        ]
        assert len(recipe_keys) == len(set(recipe_keys))
        assert loaded["total_recipe_count"] == len(recipe_keys)
    finally:
        meister.load_catalog.cache_clear()
