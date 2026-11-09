import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.data_loader import load_history, load_market, parse_date  # noqa: E402
from app.estimator import Estimator  # noqa: E402
from app.main import app  # noqa: E402
from app.models import EstimateRequest  # noqa: E402

client = TestClient(app)


def test_quality_drops_noise():
    projects, rep = load_history()
    assert rep.projects > 20
    assert rep.dropped["не работа по задаче (встречи)"] == 6
    assert rep.dropped["нулевая или пустая трудоёмкость"] == 3
    assert all(p.total_hours > 0 for p in projects)


def test_parse_excel_serial_and_iso():
    assert parse_date("46226.398194444446").year == 2026
    assert parse_date("2026-03-10").month == 3
    assert parse_date("") is None


def test_similar_task_has_analogs_and_ordered_ranges():
    est = Estimator(*[load_history()[0], load_market()])
    r = est.estimate(EstimateRequest(description="портал заявок с согласованием и интеграция с 1С"))
    assert r["analogs"] and r["analogs"][0]["similarity"] > 0.2
    for who in ("internal", "contractor"):
        s = r["scenarios"][who]
        assert s["low"]["cost"] < s["mid"]["cost"] < s["high"]["cost"]
        assert s["low"]["days"] <= s["mid"]["days"] <= s["high"]["days"]
    assert any("внешн" in x.lower() for x in r["risks"])


def test_unknown_task_falls_back_with_low_confidence():
    est = Estimator(*[load_history()[0], load_market()])
    r = est.estimate(EstimateRequest(description="qqqq zzzz wwww rrrr"))
    assert r["analogs"] == []
    assert r["confidence"]["label"] == "низкая"
    assert r["scenarios"]["internal"]["mid"]["hours"] > 0


def test_extra_costs_and_complexity_scale_result():
    est = Estimator(*[load_history()[0], load_market()])
    base = est.estimate(EstimateRequest(description="модуль отчетности с дашбордом"))
    more = est.estimate(EstimateRequest(
        description="модуль отчетности с дашбордом", complexity=1.5,
        extra_costs=[{"name": "сервер", "amount": 100000, "scenario": "internal"}]))
    assert more["scenarios"]["internal"]["mid"]["cost"] > base["scenarios"]["internal"]["mid"]["cost"] + 100000
    assert more["scenarios"]["contractor"]["mid"]["hours"] > base["scenarios"]["contractor"]["mid"]["hours"]


def test_api():
    assert client.get("/").status_code == 200
    assert "defaults" in client.get("/api/meta").json()
    ok = client.post("/api/estimate", json={"description": "телеграм-бот для уведомлений"})
    assert ok.status_code == 200 and "recommendation" in ok.json()
    assert client.post("/api/estimate", json={"description": "коротко"}).status_code == 422
    assert client.post("/api/estimate", json={"description": "нормальное описание задачи", "complexity": 9}).status_code == 422
