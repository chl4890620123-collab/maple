import os
import tempfile


def test_excel_reference_values():
    with tempfile.TemporaryDirectory() as d:
        os.environ["DB_PATH"] = os.path.join(d, "test.db")
        from app import config
        config.DB_PATH = os.environ["DB_PATH"]
        from app import db, service
        db.DB_PATH = os.environ["DB_PATH"]
        db.init_db()
        rows = {x["name"]: x for x in service.calculations(0.05)}
        assert round(rows["영원한 환생의 불꽃"]["batch_cost"]) == 2497000
        assert round(rows["강력한 환생의 불꽃"]["batch_cost"]) == 701000
        assert round(rows["마이스터링"]["batch_cost"]) == 20990000
        assert round(rows["마이스터숄더"]["batch_cost"]) == 16140000
        assert round(rows["마이스터이어링"]["batch_cost"]) == 192378960
        assert round(rows["마법의 숫돌"]["batch_cost"]) == 3700000
        assert round(rows["고급 보스 킬러의 비약"]["batch_cost"]) == 3295000
