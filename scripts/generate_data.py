"""Генерация СИНТЕТИЧЕСКИХ демо-данных.

1) data/itsm_history.csv  - выгрузка в формате ITSM/HelpDesk (те же поля, что в
   "Выгрузка полей.xlsx"): каждая строка = работа (IM), привязанная к изменению (CR).
2) data/market_rates.csv  - ориентировочные ставки подрядчиков по этапам.

ВАЖНО: все числа выдуманы для демонстрации. Для реального использования файлы
заменяются выгрузкой из ITSM и данными из открытых прайсов подрядчиков.
Запуск: python scripts/generate_data.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
rnd = random.Random(2026)

# Каталог функций веб-приложения: (название, описание, часы по этапам)
FEATURES = {
    "auth": ("Авторизация и роли пользователей", "регистрация, вход, ролевая модель доступа",
             dict(analysis=8, design=6, backend=24, frontend=14, testing=10, deploy=2, docs=3)),
    "cabinet": ("Личный кабинет клиента", "профиль клиента, история обращений, уведомления",
                dict(analysis=10, design=12, backend=28, frontend=36, testing=14, deploy=3, docs=4)),
    "requests": ("Портал заявок", "создание, согласование и статусы заявок, комментарии, вложения",
                 dict(analysis=14, design=12, backend=44, frontend=34, testing=20, deploy=3, docs=5)),
    "reports": ("Модуль отчетности", "аналитические отчеты, фильтры, выгрузка в Excel, дашборд",
                dict(analysis=10, design=8, backend=30, frontend=26, testing=14, deploy=2, docs=4)),
    "admin": ("Административная панель", "управление справочниками, пользователями и настройками",
              dict(analysis=8, design=8, backend=22, frontend=24, testing=10, deploy=2, docs=3)),
    "integr1c": ("Интеграция с 1С", "обмен данными с 1С по API, номенклатура и контрагенты",
                 dict(analysis=12, design=8, integration=46, backend=14, testing=18, deploy=4, docs=5)),
    "integrapi": ("Интеграция со сторонним сервисом", "подключение внешнего REST API, обработка ошибок и очередей",
                  dict(analysis=8, design=6, integration=30, backend=10, testing=12, deploy=3, docs=3)),
    "payments": ("Онлайн-оплата", "подключение платежного шлюза, чеки, возвраты",
                 dict(analysis=10, design=8, integration=34, backend=22, frontend=12, testing=20, deploy=3, docs=4)),
    "bot": ("Телеграм-бот", "бот для уведомлений и быстрых действий пользователей",
            dict(analysis=6, design=4, backend=26, testing=10, deploy=2, docs=2)),
    "catalog": ("Каталог и поиск", "каталог позиций, поиск, фильтры, карточка позиции",
                dict(analysis=8, design=10, backend=24, frontend=30, testing=12, deploy=2, docs=3)),
    "migration": ("Миграция данных", "перенос данных из старой системы, сверка и очистка",
                  dict(analysis=12, design=6, backend=28, testing=18, deploy=6, docs=4)),
    "workflow": ("Согласование документов", "маршруты согласования, электронные подписи, уведомления",
                 dict(analysis=16, design=10, backend=42, frontend=26, testing=20, deploy=3, docs=5)),
}
STAGE_ACTIVITY = {
    "analysis": "Разработка ФС", "design": "Проектирование", "backend": "Разработка backend",
    "frontend": "Разработка frontend", "integration": "Интеграция", "testing": "Тестирование",
    "deploy": "Внедрение", "docs": "Документация",
}
GROUPS = ["Л3. Веб-разработка", "Л3. Разработка BPMSoft", "Л3. Интеграции"]
PEOPLE = [f"Специалист {i}" for i in range(1, 9)]
PREFIXES = ["Разработка", "Реализация", "Доработка", "Создание"]


def build_history() -> list[dict]:
    rows = []
    im = 520000
    cr = 26000
    for _ in range(46):
        keys = rnd.sample(list(FEATURES), rnd.choice([1, 2, 2, 3, 3, 4]))
        cr += rnd.randint(1, 90)
        title = f"{rnd.choice(PREFIXES)}: " + "; ".join(FEATURES[k][0] for k in keys)
        descr = " ".join(FEATURES[k][1] + "." for k in keys)
        group = rnd.choice(GROUPS)
        created = date(2025, 9, 1) + timedelta(days=rnd.randint(0, 330))
        scale = rnd.uniform(0.8, 1.35)  # общая "сложность" конкретного изменения
        stage_hours: dict[str, float] = {}
        for k in keys:
            for st, h in FEATURES[k][2].items():
                stage_hours[st] = stage_hours.get(st, 0) + h
        total_plan = sum(stage_hours.values())
        cursor = created
        for st, h in stage_hours.items():
            plan = round(h * rnd.uniform(0.85, 1.0), 1)
            fact = round(h * scale * rnd.uniform(0.9, 1.15), 2)
            span = max(1, int(fact / 5))
            planned_end = cursor + timedelta(days=span + rnd.randint(1, 4))
            actual_end = cursor + timedelta(days=span + rnd.randint(0, 6))
            im += rnd.randint(1, 40)
            rows.append({
                "Номер": f"IM{im:08d}", "Изменение.Номер": f"CR{cr:08d}", "Вид": "",
                "Заголовок": f"CR{cr:08d}: {title}", "Специалист": rnd.choice(PEOPLE),
                "Рабочая группа": group, "Состояние": "Завершена",
                "Тип активности ЗНИ": STAGE_ACTIVITY[st], "Дата создания": cursor.isoformat(),
                "Описание": descr, "Плановая дата завершения": planned_end.isoformat(),
                "Фактическое завершение": actual_end.isoformat(),
                "Дата изменения": actual_end.isoformat(),
                "Фактическая трудоемкость (часов)": fact, "Плановая трудоемкость (часов)": plan,
                "Заквотированное время, часы": round(plan, 1),
            })
            cursor = cursor + timedelta(days=max(1, span // 2))
        _ = total_plan
    # "Мусор", который должна отсеять проверка качества (как в реальной выгрузке)
    for i in range(6):
        im += 3
        rows.append({
            "Номер": f"IM{im:08d}", "Изменение.Номер": f"CR{29000 + i:08d}", "Вид": "",
            "Заголовок": "Встречи", "Специалист": rnd.choice(PEOPLE), "Рабочая группа": GROUPS[1],
            "Состояние": "Завершена", "Тип активности ЗНИ": "Реализация изменения",
            "Дата создания": "2026-03-10", "Описание": "", "Плановая дата завершения": "2026-03-10",
            "Фактическое завершение": "2026-03-10", "Дата изменения": "2026-03-10",
            "Фактическая трудоемкость (часов)": 1.33, "Плановая трудоемкость (часов)": 2,
            "Заквотированное время, часы": 0,
        })
    for i in range(3):
        im += 3
        rows.append({
            "Номер": f"IM{im:08d}", "Изменение.Номер": f"CR{27000 + i:08d}", "Вид": "",
            "Заголовок": f"CR{27000 + i:08d}: Оценка трудоёмкости по КЕ", "Специалист": rnd.choice(PEOPLE),
            "Рабочая группа": GROUPS[0], "Состояние": "Завершена",
            "Тип активности ЗНИ": "Оценка трудоёмкости", "Дата создания": "2026-04-02", "Описание": "",
            "Плановая дата завершения": "2026-04-08", "Фактическое завершение": "2026-04-02",
            "Дата изменения": "2026-04-02", "Фактическая трудоемкость (часов)": 0,
            "Плановая трудоемкость (часов)": 0, "Заквотированное время, часы": 0,
        })
    return rows


# Ставки подрядчиков, руб/час (ДЕМО-значения; заменить данными из открытых прайсов)
RATE_BASE = {"analysis": 3800, "design": 3600, "backend": 4200, "frontend": 3900,
             "integration": 4800, "testing": 2900, "deploy": 3500, "docs": 2600}


def build_market() -> list[dict]:
    rows = []
    for i, (kind, factor) in enumerate([
        ("Студия веб-разработки", 0.85), ("Студия веб-разработки", 0.95), ("Студия веб-разработки", 1.05),
        ("Интегратор", 1.15), ("Интегратор", 1.3), ("Аутсорс-компания", 0.9),
        ("Аутсорс-компания", 1.0), ("Крупный вендор", 1.5),
    ], 1):
        for st, base in RATE_BASE.items():
            rate = round(base * factor * rnd.uniform(0.95, 1.05) / 50) * 50
            rows.append({
                "source_id": f"SRC{i:02d}", "company_type": kind, "stack": "Python/Web",
                "stage": st, "rate_rub_hour": rate,
                "year": 2026, "note": "демо-данные: заменить ссылкой на открытый прайс",
            })
    # соседние стеки (для проверки нормализации по стеку): база - SRC06 (аутсорс x1.0)
    base_rows = [r for r in rows if r["source_id"] == "SRC06"]
    for i, (stack, mult) in enumerate([("1C", 1.15), ("Java/Enterprise", 1.2), ("Mobile", 1.1)], start=9):
        for r in base_rows:
            n = dict(r)
            n["source_id"] = f"SRC{i:02d}"
            n["stack"] = stack
            # базовая ставка источника (без множителя стека) + шум выборки: медиана выборки
            # восстанавливает множитель из config.STACK_MULTIPLIERS при нормализации select_market
            n["rate_rub_hour"] = round(float(r["rate_rub_hour"]) * mult * rnd.uniform(0.85, 1.15) / 50) * 50
            rows.append(n)
    # устаревший прайс и битая строка - должны отсеиваться загрузчиком (как в реальных данных)
    for r in rows[:8]:
        old = dict(r); old.update({"source_id": "SRC00", "year": 2022,
                                   "note": "демо: устаревший прайс (отсекается фильтром года)"})
        rows.append(old)
    rows.append({"source_id": "", "company_type": "Студия веб-разработки", "stack": "Python/Web",
                 "stage": "backend", "rate_rub_hour": 0, "year": 2026,
                 "note": "демо: битая строка (отсекается проверкой качества)"})
    return rows


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    h, m = build_history(), build_market()
    write(DATA / "itsm_history.csv", h)
    write(DATA / "market_rates.csv", m)
    print(f"itsm_history.csv: {len(h)} строк; market_rates.csv: {len(m)} строк")
