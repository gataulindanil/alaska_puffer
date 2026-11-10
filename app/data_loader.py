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


@dataclass
class MarketRow:
    source_id: str
    company_type: str
    stack: str
    stage: str
    rate: float
    year: int | None
    note: str


def load_market_rows(path: Path | None = None) -> tuple[list[MarketRow], QualityReport]:
    """Построчная загрузка прайсов с проверкой качества (прослеживаемость: source_id, note)."""
    path = path or config.DATA_DIR / "market_rates.csv"
    rep = QualityReport()
    rows: list[MarketRow] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rep.total_rows += 1
            stage = (row.get("stage") or "").strip()
            r = _num(row.get("rate_rub_hour"))
            y = _num(row.get("year"))
            if not (row.get("source_id") or "").strip():
                rep.dropped["нет источника (source_id)"] += 1
            elif stage not in config.STAGES:
                rep.dropped["неизвестный этап"] += 1
            elif r is None or r <= 0:
                rep.dropped["пустая или нулевая ставка"] += 1
            elif y is not None and y < config.MARKET_MIN_YEAR:
                rep.dropped[f"прайс старше {config.MARKET_MIN_YEAR} г."] += 1
            else:
                rows.append(MarketRow(source_id=row["source_id"].strip(),
                                      company_type=(row.get("company_type") or "").strip(),
                                      stack=(row.get("stack") or "").strip(), stage=stage, rate=r,
                                      year=int(y) if y else None, note=(row.get("note") or "").strip()))
                rep.used_rows += 1
    return rows, rep


def market_stats(vals: list[float]) -> dict[str, float]:
    q = statistics.quantiles(vals, n=4, method="inclusive") if len(vals) >= 2 else [vals[0]] * 3
    return {"p25": q[0], "p50": q[1], "p75": q[2], "n": len(vals)}


def _weighted_quantiles(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """Квартили p25/p50/p75 с весами источников (нормализация по представительности выборки)."""
    pts = sorted((v, w) for v, w in pairs)
    total = sum(w for _, w in pts)
    out = {}
    for q, name in ((0.25, "p25"), (0.5, "p50"), (0.75, "p75")):
        acc = 0.0
        for v, w in pts:
            acc += w
            if acc >= q * total:
                out[name] = v
                break
    out["n"] = len(pts)
    return out


def select_market(rows: list[MarketRow], req) -> tuple[dict[str, dict[str, float]], dict]:
    """Нормализация рыночных условий: фильтр по стеку/типу подрядчика/году + корректирующие множители.

    Множители (config.STACK_MULTIPLIERS / COMPANY_TYPE_MULTIPLIERS) приводят ставки
    выбранных источников к профилю задачи (стек, тип исполнителя), поэтому в выборку
    могут попадать и «соседние» стеки — это отражено в returned info для объяснимости.
    """
    years = sorted({r.year for r in rows if r.year}, reverse=True)
    wanted_year = req.market_year or (years[0] if years else config.MARKET_MIN_YEAR)
    # если выбранного года нет в данных, берём ближайший доступный (и фиксируем это в объяснении)
    effective_year = wanted_year if wanted_year in years else (years[0] if years else None)
    year_note = ""
    if effective_year != wanted_year and effective_year is not None:
        year_note = f"прайсов за {wanted_year} г. нет, взяты данные за {effective_year} г."
    types = set(req.company_types)
    used, excluded = [], []
    for r in rows:
        factor = r.rate
        factor *= req.market_index_pct / 100.0
        if r.year:  # дефлятор: пересчёт ставок старых прайсов к базовому году (калибруется константой)
            factor *= config.DEFLATOR_BASE_PRICE ** ((config.DEFLATOR_BASE_YEAR - r.year) / 2.0)
        factor *= config.STACK_MULTIPLIERS.get(r.stack, 1.0)
        factor /= config.STACK_MULTIPLIERS.get(req.stack, 1.0)
        factor *= config.COMPANY_TYPE_MULTIPLIERS.get(r.company_type, 1.0)
        factor /= config.COMPANY_TYPE_MULTIPLIERS.get(req.company_type_profile, 1.0)
        adj = MarketRow(r.source_id, r.company_type, r.stack, r.stage, factor, r.year, r.note)
        reasons = []
        if r.year != effective_year:
            reasons.append(f"год {r.year} != {effective_year}")
        if types and r.company_type not in types:
            reasons.append(f"тип «{r.company_type}» не выбран")
        if reasons:
            excluded.append({"source_id": r.source_id, "stage": r.stage, "reason": "; ".join(reasons)})
        else:
            used.append(adj)
    by_stage: dict[str, list[float]] = defaultdict(list)
    for r in used:
        by_stage[r.stage].append(r.rate)
    # взвешенные квартили: источники по стеку задачи весомее «соседних» стеков
    w_by_stage: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in used:
        w = config.STACK_WEIGHT if r.stack == req.stack else 1.0
        w_by_stage[r.stage].append((r.rate, w))
    stats = {st: _weighted_quantiles(pairs) for st, pairs in w_by_stage.items()}
    sources = sorted({(r.source_id, r.company_type, r.stack) for r in used}, key=lambda x: x[0])
    info = {
        "year": effective_year,
        "requested_year": wanted_year,
        "available_years": years,
        "stack": req.stack,
        "company_type_profile": req.company_type_profile,
        "company_types_filter": sorted(types) if types else "все типы",
        "index_pct": req.market_index_pct,
        "year_note": year_note,
        "sources": [{"source_id": s, "company_type": ct, "stack": st} for s, ct, st in sources],
        "used_rows": len(used),
        "excluded_rows": len(excluded),
        "excluded_examples": excluded[:5],
        "normalization": ("ставка x индекс рынка x множитель стека источника / множитель стека задачи "
                          "x множитель типа источника / множитель типа задачи"),
    }
    return stats, info
