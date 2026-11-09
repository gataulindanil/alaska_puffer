"""Загрузка источников, проверка качества и сборка "проектов" (CR -> работы по этапам)."""
from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

F_IM, F_CR, F_TITLE = "Номер", "Изменение.Номер", "Заголовок"
F_ACT, F_DESC, F_GROUP = "Тип активности ЗНИ", "Описание", "Рабочая группа"
F_CREATED, F_DONE = "Дата создания", "Фактическое завершение"
F_FACT, F_PLAN = "Фактическая трудоемкость (часов)", "Плановая трудоемкость (часов)"


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


def parse_date(v) -> date | None:
    """Принимает ISO-дату или серийный номер Excel (как в исходной выгрузке)."""
    s = str(v).strip()
    if not s:
        return None
    n = _num(s)
    if n is not None and n > 30000:
        return (datetime(1899, 12, 30) + timedelta(days=n)).date()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


@dataclass
class Project:
    cr: str
    title: str
    description: str
    group: str
    stage_hours: dict[str, float] = field(default_factory=dict)   # факт
    plan_hours: float = 0.0
    work_count: int = 0
    calendar_days: int | None = None

    @property
    def total_hours(self) -> float:
        return sum(self.stage_hours.values())

    @property
    def text(self) -> str:
        return f"{self.title} {self.description}"


@dataclass
class QualityReport:
    total_rows: int = 0
    used_rows: int = 0
    dropped: Counter = field(default_factory=Counter)
    projects: int = 0
    fact_plan_ratio: float | None = None
    unknown_activities: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total_rows, "used_rows": self.used_rows,
            "dropped": dict(self.dropped), "projects": self.projects,
            "fact_plan_ratio": self.fact_plan_ratio,
            "unknown_activities": self.unknown_activities,
        }


def load_history(path: Path | None = None) -> tuple[list[Project], QualityReport]:
    path = path or config.DATA_DIR / "itsm_history.csv"
    rep = QualityReport()
    by_cr: dict[str, Project] = {}
    spans: dict[str, list[date]] = defaultdict(list)
    unknown: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rep.total_rows += 1
            cr = (row.get(F_CR) or "").strip()
            title = (row.get(F_TITLE) or "").strip()
            fact, plan = _num(row.get(F_FACT)), _num(row.get(F_PLAN))
            act = (row.get(F_ACT) or "").strip()
            if not cr:
                rep.dropped["нет номера изменения"] += 1
            elif any(n in title.lower() for n in config.NOISE_TITLES):
                rep.dropped["не работа по задаче (встречи)"] += 1
            elif fact is None or fact <= 0:
                rep.dropped["нулевая или пустая трудоёмкость"] += 1
            elif act not in config.ACTIVITY_TO_STAGE:
                rep.dropped["неизвестный тип активности"] += 1
                unknown.add(act or "(пусто)")
            else:
                stage = config.ACTIVITY_TO_STAGE[act]
                p = by_cr.setdefault(cr, Project(
                    cr=cr, title=title.split(":", 1)[-1].strip(),
                    description=(row.get(F_DESC) or "").strip(), group=(row.get(F_GROUP) or "").strip()))
                p.stage_hours[stage] = p.stage_hours.get(stage, 0.0) + fact
                p.plan_hours += plan or 0.0
                p.work_count += 1
                rep.used_rows += 1
                for k in (F_CREATED, F_DONE):
                    d = parse_date(row.get(k))
                    if d:
                        spans[cr].append(d)
    for cr, p in by_cr.items():
        if spans[cr]:
            p.calendar_days = (max(spans[cr]) - min(spans[cr])).days + 1
    projects = [p for p in by_cr.values() if p.total_hours > 0]
    rep.projects = len(projects)
    plan_total = sum(p.plan_hours for p in projects)
    if plan_total > 0:
        rep.fact_plan_ratio = round(sum(p.total_hours for p in projects) / plan_total, 2)
    rep.unknown_activities = sorted(unknown)
    return projects, rep


def load_market(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Ставки подрядчиков по этапам: квартили p25 / p50 / p75 (руб/час)."""
    path = path or config.DATA_DIR / "market_rates.csv"
    by_stage: dict[str, list[float]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            r = _num(row.get("rate_rub_hour"))
            if r and r > 0 and row.get("stage") in config.STAGES:
                by_stage[row["stage"]].append(r)
    out = {}
    for st, vals in by_stage.items():
        q = statistics.quantiles(vals, n=4, method="inclusive") if len(vals) >= 2 else [vals[0]] * 3
        out[st] = {"p25": q[0], "p50": q[1], "p75": q[2], "n": len(vals)}
    return out
