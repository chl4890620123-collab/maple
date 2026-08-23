import json
import os
import tempfile
from pathlib import Path


def _configure_sqlite(db_path: str):
    os.environ["DB_ENGINE"] = "sqlite"
    os.environ["DB_PATH"] = db_path
    from app import config
    config.DB_ENGINE = "sqlite"
    config.DB_PATH = db_path
    from app import db, service
    db.DB_PATH = db_path if hasattr(db, "DB_PATH") else db_path
    return db, service


def test_excel_reference_values():
    with tempfile.TemporaryDirectory() as d:
        db, service = _configure_sqlite(os.path.join(d, "test.db"))
        db.init_db()
        rows = {x["name"]: x for x in service.calculations(0.05)}
        assert round(rows["영원한 환생의 불꽃"]["batch_cost"]) == 2497000
        assert round(rows["강력한 환생의 불꽃"]["batch_cost"]) == 701000
        assert round(rows["마이스터링"]["batch_cost"]) == 20990000
        assert round(rows["마이스터숄더"]["batch_cost"]) == 16140000
        assert round(rows["마이스터이어링"]["batch_cost"]) == 192378960
        assert round(rows["마법의 숫돌"]["batch_cost"]) == 3700000
        assert round(rows["고급 보스 킬러의 비약"]["batch_cost"]) == 3295000


def test_seed_is_valid_utf8_json():
    seed_path = Path(__file__).resolve().parent.parent / "data" / "seed.json"
    text = seed_path.read_bytes().decode("utf-8")
    seed = json.loads(text)
    names = {item["name"] for item in seed["items"]}
    assert "마이스터올마이티링" in names
    assert "영원한 환생의 불꽃" in names


def test_legacy_mojibake_repair():
    with tempfile.TemporaryDirectory() as d:
        db, _ = _configure_sqlite(os.path.join(d, "repair.db"))
        broken = "태초의 정수".encode("utf-8").decode("latin1")
        assert db.repair_mojibake(broken) == "태초의 정수"
