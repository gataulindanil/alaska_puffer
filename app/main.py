from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as c
from .data_loader import load_history, load_market_rows, select_market
from .estimator import Estimator
from .models import EstimateRequest

app = FastAPI(title="Сравнение: своя команда vs подрядчик", version="0.2.0")

projects, quality = load_history()
market_rows, market_quality = load_market_rows()
estimator = Estimator(projects, market_rows)


@app.get("/api/meta")
def meta():
    # базовая рыночная сводка для демо-запроса (без фильтров), для отображения в UI
    demo_req = EstimateRequest(description="демонстрационная задача без фильтров рынка")
    market_stats, _ = select_market(market_rows, demo_req)
    return {
        "defaults": c.DEFAULTS, "stages": c.STAGES,
        "quality": {"history": quality.as_dict(), "market": market_quality.as_dict()},
        "market": market_stats,
        "stacks": c.MARKET_STACKS, "company_types": c.MARKET_COMPANY_TYPES,
        "examples": [
            "Нужен портал заявок для сотрудников с согласованием и личным кабинетом, плюс интеграция с 1С.",
            "Модуль отчетности с дашбордом и выгрузкой в Excel для руководителей.",
            "Телеграм-бот для уведомлений и онлайн-оплата услуг клиентами.",
        ],
    }


@app.post("/api/estimate")
def estimate(req: EstimateRequest):
    return estimator.estimate(req)


@app.get("/")
def index():
    return FileResponse(c.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=c.STATIC_DIR), name="static")
