from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as c
from .data_loader import load_history, load_market
from .estimator import Estimator
from .models import EstimateRequest

app = FastAPI(title="Сравнение: своя команда vs подрядчик", version="0.1.0")

projects, quality = load_history()
market = load_market()
estimator = Estimator(projects, market)


@app.get("/api/meta")
def meta():
    return {
        "defaults": c.DEFAULTS, "stages": c.STAGES, "quality": quality.as_dict(),
        "market": market,
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
