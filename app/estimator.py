"""Расчёт: аналоги из истории -> часы по этапам -> стоимость и срок для двух сценариев."""
from __future__ import annotations

import math
import re
from collections import Counter

from . import config as c
from .data_loader import Project, select_market
from .models import EstimateRequest

_TOKEN = re.compile(r"[а-яёa-z0-9]+")
_STOP = {"для", "что", "как", "при", "это", "или", "над", "под", "его", "ее", "её", "они", "все", "все"}


def tokens(text: str) -> list[str]:
    """Грубая нормализация: нижний регистр и усечение слова до 6 символов (замена стеммера)."""
    return [w[:6] for w in _TOKEN.findall(text.lower()) if len(w) >= 3 and w not in _STOP]


class Estimator:
    def __init__(self, projects: list[Project], market_rows):
        self.projects = projects
        self.market_rows = market_rows  # построчные прайсы; квартили считаются на запрос (см. select_market)
        self._docs = [Counter(tokens(p.text)) for p in projects]
        df: Counter = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = max(len(projects), 1)
        self._idf = {t: math.log((1 + n) / (1 + k)) + 1 for t, k in df.items()}
        self._vecs = [self._vec(d) for d in self._docs]

    def _vec(self, counts: Counter) -> dict[str, float]:
        v = {t: (1 + math.log(k)) * self._idf.get(t, 1.0) for t, k in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def find_analogs(self, text: str) -> list[tuple[Project, float]]:
        q = self._vec(Counter(tokens(text)))
        scored = []
        for p, v in zip(self.projects, self._vecs):
            sim = sum(w * v.get(t, 0.0) for t, w in q.items())
            if sim >= c.MIN_SIMILARITY:
                scored.append((p, sim))
        scored.sort(key=lambda x: -x[1])
        return scored[: c.TOP_K]

    # ---- часы по этапам ----------------------------------------------------
    def _hours(self, analogs, complexity):
        if analogs:
            wsum = sum(s for _, s in analogs)
            mix = {st: sum(p.stage_hours.get(st, 0) * s for p, s in analogs) / wsum for st in c.STAGES}
            totals = [p.total_hours for p, _ in analogs]
            mean = sum(t * s for t, (_, s) in zip(totals, analogs)) / wsum
            var = sum(s * (t - mean) ** 2 for t, (_, s) in zip(totals, analogs)) / wsum
            cv = math.sqrt(var) / mean if mean else 0.5
        else:
            mix = {st: c.FALLBACK_TOTAL_HOURS * share for st, share in c.FALLBACK_MIX.items()}
            cv = 0.5
        mix = {st: h * complexity for st, h in mix.items()}
        low_k = 1 - min(0.35, max(0.15, cv))
        high_k = 1 + min(0.7, max(0.25, 1.5 * cv))
        return mix, low_k, high_k, cv

    @staticmethod
    def _confidence(analogs, cv):
        top = analogs[0][1] if analogs else 0.0
        score = 0.5 * min(1, top / 0.6) + 0.25 * min(1, len(analogs) / c.TOP_K) + 0.25 * (1 - min(1, cv / 0.6))
        if not analogs:
            score = min(score, 0.2)
        label = "высокая" if score >= 0.7 else "средняя" if score >= 0.45 else "низкая"
        return round(score, 2), label

    # ---- основной расчёт -----------------------------------------------------
    def estimate(self, req: EstimateRequest) -> dict:
        analogs = self.find_analogs(req.description)
        mix, low_k, high_k, cv = self._hours(analogs, req.complexity)
        score, label = self._confidence(analogs, cv)
        mid_total = sum(mix.values())
        scen = {"low": low_k, "mid": 1.0, "high": high_k}

        market, market_info = select_market(self.market_rows, req)

        rate_int = req.internal_rate * (1 + req.internal_overhead_pct / 100)
        risk = 1 + req.risk_reserve_pct / 100
        extra = {s: sum(e.amount for e in req.extra_costs if e.scenario in (s, "both"))
                 for s in ("internal", "contractor")}
        qkey = {"low": "p25", "mid": "p50", "high": "p75"}
        fallback_rate = (sum(m["p50"] for m in market.values()) / len(market)) if market else 4000.0

        stages, internal, contractor = [], {}, {}
        for st, name in c.STAGES.items():
            h = mix.get(st, 0.0)
            if h <= 0:
                continue
            stages.append({
                "stage": st, "name": name, "hours": round(h, 1),
                "internal_cost": round(h * rate_int),
                "contractor_hours": round(h * req.contractor_efficiency, 1),
                "contractor_rate": round(market.get(st, {}).get("p50", fallback_rate)),
                "contractor_cost": round(h * req.contractor_efficiency * market.get(st, {}).get("p50", fallback_rate)),
            })

        for k, kf in scen.items():
            h_int = mid_total * kf
            cost_int = h_int * rate_int * risk + extra["internal"]
            h_ctr = h_int * req.contractor_efficiency
            ctr_work = sum(mix.get(st, 0) * kf * req.contractor_efficiency *
                           market.get(st, {}).get(qkey[k], fallback_rate) for st in c.STAGES)
            coord_hours = h_int * req.coordination_pct / 100
            cost_ctr = (ctr_work + coord_hours * rate_int) * risk + extra["contractor"]
            internal[k] = {
                "hours": round(h_int), "cost": round(cost_int),
                "days": round(req.internal_queue_days + h_int / (req.internal_team * c.FOCUS_HOURS_PER_DAY)),
            }
            contractor[k] = {
                "hours": round(h_ctr), "customer_hours": round(coord_hours), "cost": round(cost_ctr),
                "days": round(req.contractor_mobilization_days + h_ctr / (req.contractor_team * c.FOCUS_HOURS_PER_DAY)),
            }

        return {
            "scenarios": {"internal": internal, "contractor": contractor},
            "stages": stages,
            "market": market_info,
            "analogs": [{
                "cr": p.cr, "title": p.title, "similarity": round(s, 2),
                "hours": round(p.total_hours), "calendar_days": p.calendar_days, "works": p.work_count,
            } for p, s in analogs],
            "confidence": {"score": score, "label": label, "analog_count": len(analogs),
                           "spread_cv": round(cv, 2)},
            "assumptions": self._assumptions(req, analogs, low_k, high_k, market_info),
            "risks": self._risks(req, analogs, label, market_info),
            "recommendation": self._recommendation(internal, contractor, label),
        }

    # ---- объяснимость --------------------------------------------------------
    @staticmethod
    def _assumptions(req, analogs, low_k, high_k, minfo=None):
        src = (f"Часы по этапам = взвешенное среднее по {len(analogs)} похожим изменениям из истории "
               "(вес = сходство описаний)." if analogs else
               f"Похожих изменений в истории нет: взята базовая оценка {c.FALLBACK_TOTAL_HOURS:.0f} ч с типовым распределением по этапам.")
        out = [
            src,
            f"Диапазон часов: от x{low_k:.2f} до x{high_k:.2f} к ожидаемому значению (по разбросу аналогов).",
            f"Множитель сложности: x{req.complexity:.2f}.",
            f"Внутренняя стоимость часа: {req.internal_rate:.0f} руб. + накладные {req.internal_overhead_pct:.0f}%.",
            f"Подрядчик: ставки по этапам - квартили рынка (мин = p25, ожид. = p50, макс = p75); затрачивает {req.contractor_efficiency:.0%} "
            "от внутренних часов (готовые решения и опыт).",
            f"Работы заказчика при подрядчике (ТЗ, приёмка, управление): {req.coordination_pct:.0f}% часов по внутренней ставке.",
            f"Резерв на риски: {req.risk_reserve_pct:.0f}% к обоим сценариям; доп. расходы резервом не облагаются.",
            f"Срок = часы / (люди x {c.FOCUS_HOURS_PER_DAY:.0f} продуктивных ч/день) + ожидание старта "
            f"(внутри {req.internal_queue_days} р.д., подрядчик {req.contractor_mobilization_days} р.д.).",
        ]
        if minfo:
            out.append(
                f"Рынок: выборка {minfo['used_rows']} строк прайсов, год {minfo['year']}, стек задачи «{minfo['stack']}», "
                f"профиль подрядчика «{minfo['company_type_profile']}», фильтр типов: {minfo['company_types_filter']}, "
                f"индекс рынка {minfo['index_pct']:.0f}%; исключено строк: {minfo['excluded_rows']}.")
        return out

    @staticmethod
    def _risks(req, analogs, label, minfo=None):
        text = req.description.lower()
        out = [msg for keys, msg in c.RISK_RULES if any(k in text for k in keys)]
        if len(analogs) < 3:
            out.append("Мало аналогов в истории: оценка опирается на ограниченную базу, диапазон шире.")
        if label == "низкая":
            out.append("Низкая достоверность: перед решением нужны запросы подрядчикам и уточнение требований.")
        if minfo and minfo["used_rows"] < 20:
            out.append(f"Малая рыночная выборка ({minfo['used_rows']} строк): диапазон ставок может быть нерепрезентативным.")
        if minfo and minfo["excluded_rows"]:
            out.append("Часть прайсов исключена фильтрами (год/тип подрядчика) — при расширении выборки ставка может измениться.")
        out.append("Внутренняя команда: доступность специалистов и конкуренция за ресурсы с текущими задачами.")
        out.append("Подрядчик: зависимость от внешней команды, передача знаний и поддержка после сдачи.")
        return out

    @staticmethod
    def _recommendation(internal, contractor, label):
        i, k = internal["mid"], contractor["mid"]
        diff = (k["cost"] - i["cost"]) / i["cost"] * 100 if i["cost"] else 0
        cheaper = "внутренняя команда" if i["cost"] <= k["cost"] else "подрядчик"
        faster = "внутренняя команда" if i["days"] <= k["days"] else "подрядчик"
        overlap = max(internal["low"]["cost"], contractor["low"]["cost"]) <= min(internal["high"]["cost"], contractor["high"]["cost"])
        text = (f"По ожидаемой стоимости дешевле: {cheaper} (разница {abs(diff):.0f}%); по сроку быстрее: {faster}. ")
        if overlap:
            text += "Диапазоны стоимости пересекаются, поэтому решающими станут не цена, а срок, загрузка команды и необходимость поддержки. "
        text += f"Достоверность оценки: {label}. Это оценка верхнего уровня; для решения запросите КП у подрядчиков."
        return {"cheaper": cheaper, "faster": faster, "cost_diff_pct": round(diff), "ranges_overlap": overlap, "text": text}
