import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.data_loader import load_history, load_market_rows, parse_date  # noqa: E402
from app.estimator import Estimator  # noqa: E402
from app.main import app  # noqa: E402
from app.models import EstimateRequest  # noqa: E402

client = TestClient(app)


def make_estimator():
    return Estimator(load_history()[0], load_market_rows()[0])


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
    est = make_estimator()
    r = est.estimate(EstimateRequest(description="портал заявок с согласованием и интеграция с 1С"))
    assert r["analogs"] and r["analogs"][0]["similarity"] > 0.2
    for who in ("internal", "contractor"):
        s = r["scenarios"][who]
        assert s["low"]["cost"] < s["mid"]["cost"] < s["high"]["cost"]
        assert s["low"]["days"] <= s["mid"]["days"] <= s["high"]["days"]
    assert any("внешн" in x.lower() for x in r["risks"])


def test_unknown_task_falls_back_with_low_confidence():
    est = make_estimator()
    r = est.estimate(EstimateRequest(description="qqqq zzzz wwww rrrr"))
    assert r["analogs"] == []
    assert r["confidence"]["label"] == "низкая"
    assert r["scenarios"]["internal"]["mid"]["hours"] > 0


def test_extra_costs_and_complexity_scale_result():
    est = make_estimator()
    base = est.estimate(EstimateRequest(description="модуль отчетности с дашбордом"))
    more = est.estimate(EstimateRequest(
        description="модуль отчетности с дашбордом", complexity=1.5,
        extra_costs=[{"name": "сервер", "amount": 100000, "scenario": "internal"}]))
    assert more["scenarios"]["internal"]["mid"]["cost"] > base["scenarios"]["internal"]["mid"]["cost"] + 100000
    assert more["scenarios"]["contractor"]["mid"]["hours"] > base["scenarios"]["contractor"]["mid"]["hours"]


def test_market_quality_and_normalization():
    rows, rep = load_market_rows()
    # битая строка (пустой source_id) отсекается загрузчиком
    assert rep.dropped.get("нет источника (source_id") == 1 or rep.dropped.get("нет источника (source_id)") == 1
    assert all(r.year is None or r.year >= 2024 for r in rows)
    est = make_estimator()
    web = est.estimate(EstimateRequest(description="портал заявок", stack="Python/Web"))
    ent = est.estimate(EstimateRequest(description="портал заявок", stack="Java/Enterprise"))
    # нормализация по стеку: ставки для дорогого стека выше при тех же часах
    assert ent["scenarios"]["contractor"]["mid"]["cost"] > web["scenarios"]["contractor"]["mid"]["cost"]
    assert ent["market"]["stack"] == "Java/Enterprise"
    # фильтр по типу подрядчика меняет выборку и стоимость
    studios = est.estimate(EstimateRequest(description="портал заявок", company_types=["Студия веб-разработки"]))
    assert studios["market"]["used_rows"] < web["market"]["used_rows"]
    assert studios["scenarios"]["contractor"]["mid"]["cost"] != web["scenarios"]["contractor"]["mid"]["cost"]
    # индекс рынка масштабирует стоимость подрядчика, внутренняя не меняется
    idx = est.estimate(EstimateRequest(description="портал заявок", market_index_pct=120))
    assert idx["scenarios"]["contractor"]["mid"]["cost"] > web["scenarios"]["contractor"]["mid"]["cost"]
    assert idx["scenarios"]["internal"]["mid"]["cost"] == web["scenarios"]["internal"]["mid"]["cost"]
    # устаревший прайс SRC00 исключается фильтром года и попадает в excluded
    assert all(s["source_id"] != "SRC00" for s in web["market"]["sources"])
    assert web["market"]["excluded_rows"] > 0
    assert any("рынок" in a.lower() for a in web["assumptions"])


def test_api():
    assert client.get("/").status_code == 200
    m = client.get("/api/meta").json()
    assert "defaults" in m and "stacks" in m and m["quality"]["market"]["total_rows"] > 0
    ok = client.post("/api/estimate", json={"description": "телеграм-бот для уведомлений"})
    assert ok.status_code == 200 and "recommendation" in ok.json() and "market" in ok.json()
    assert client.post("/api/estimate", json={"description": "коротко"}).status_code == 422
    assert client.post("/api/estimate", json={"description": "нормальное описание задачи", "complexity": 9}).status_code == 422
