"""Engine-verified synthetic charts and a fixed categorized evaluation dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.chart.calculator import calculate_chart
from app.chart.models import ChartRequest, ChartResponse

AS_OF = datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
FIXTURE_INPUTS = (
    {"chart_id": "synthetic-a", "birth_date": "1992-06-15", "birth_time": "12:30:00", "timezone": "Asia/Kolkata", "location": "Synthetic fixture A", "latitude": 13.0827, "longitude": 80.2707},
    {"chart_id": "synthetic-b", "birth_date": "2013-02-25", "birth_time": "18:00:00", "timezone": "UTC", "location": "Synthetic fixture B", "latitude": 0.0, "longitude": 0.0},
    {"chart_id": "synthetic-c", "birth_date": "2001-04-19", "birth_time": "19:20:00", "timezone": "Europe/London", "location": "Synthetic fixture C", "latitude": 51.5074, "longitude": -0.1278},
)
BASELINE_PATH = Path(__file__).resolve().parents[2] / "docs" / "eval-chart-fixtures.json"


@dataclass(frozen=True)
class TestChart:
    chart_id: str
    request: ChartRequest
    as_of: datetime
    result: ChartResponse

    @property
    def facts(self) -> tuple[str, ...]:
        return tuple(self.result.facts)


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    chart: TestChart
    category: str
    question: str
    required_terms: tuple[str, ...] = ()
    required_dates: tuple[str, ...] = ()
    division: str | None = None
    acknowledge_missing: bool = False


def _expected_snapshot(chart: ChartResponse) -> dict[str, Any]:
    return {
        "lagna_sign": chart.lagna_sign,
        "planets": {p.name: {
            "sign": p.sign, "house": p.house, "nakshatra": p.nakshatra,
            "pada": p.nakshatra_pada, "d9_sign": p.d9_sign, "d9_house": p.d9_house,
            "d10_sign": p.d10_sign, "d10_house": p.d10_house,
        } for p in chart.planets},
        "d9": {"ascendant_sign": chart.d9.ascendant_sign},
        "d10": {"ascendant_sign": chart.d10.ascendant_sign},
        "dashas": {key: {"lord": getattr(chart, key).lord,
                         "start_date": getattr(chart, key).start_date.isoformat(),
                         "end_date": getattr(chart, key).end_date.isoformat()}
                   for key in ("current_mahadasha", "current_antardasha", "current_pratyantardasha")},
        "transits": {item.planet: {"sign": item.sign, "house": item.house, "nakshatra": item.nakshatra}
                     for item in chart.transits},
    }


def synthetic_charts(*, verify_baseline: bool = True) -> tuple[TestChart, ...]:
    pinned = {}
    if verify_baseline:
        if not BASELINE_PATH.exists():
            raise RuntimeError(f"Missing verified chart fixture baseline: {BASELINE_PATH}")
        pinned = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    charts = []
    for raw in FIXTURE_INPUTS:
        request = ChartRequest(**{key: value for key, value in raw.items() if key != "chart_id"})
        result = calculate_chart(request, as_of=AS_OF)
        if verify_baseline and pinned.get(raw["chart_id"]) != _expected_snapshot(result):
            raise AssertionError(f"Chart engine output changed for {raw['chart_id']}; review and explicitly update the pinned fixture baseline")
        charts.append(TestChart(raw["chart_id"], request, AS_OF, result))
    return tuple(charts)


def _planet(chart: TestChart, name: str):
    return next(p for p in chart.result.planets if p.name == name)


def _ruler(chart: TestChart, house: int) -> str:
    fact = next(f for f in chart.facts if f"D1 house {house} sign is " in f)
    return fact.split("ruler is ", 1)[1]


def _houses_ruled(chart: TestChart, planet: str) -> tuple[str, ...]:
    return tuple(str(h) for h in range(1, 13) if _ruler(chart, h) == planet)


def _build_cases(chart: TestChart) -> list[EvalCase]:
    p = {name: _planet(chart, name) for name in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")}
    occupants_d1 = tuple(item.name for item in chart.result.planets if item.house == 2)
    tenth_lord = _ruler(chart, 10)
    tenth_lord_position = p[tenth_lord]
    occupants_d10_10 = tuple(item.name for item in chart.result.d10.planets if item.house == 10)
    house5_lord = _ruler(chart, 5)
    house10_lord = _ruler(chart, 10)
    yoga = next(f for f in chart.facts if "Budha-Aditya Yoga" in f)
    present = "present" if "is present" in yoga else "not present"
    facts = chart.result.facts
    dasha = chart.result.current_antardasha
    praty = chart.result.current_pratyantardasha
    cases: list[EvalCase] = []

    def add(case_id: str, category: str, question: str, terms: tuple[str, ...] = (), dates: tuple[str, ...] = (), division: str | None = None, missing: bool = False):
        cases.append(EvalCase(f"{chart.chart_id}-{case_id}", chart, category, question, terms, dates, division, missing))

    add("ascendant", "basic", "What is my ascendant sign?", (chart.result.lagna_sign,))
    add("moon-sign", "basic", "What is my Moon sign?", (p["Moon"].sign,))
    add("moon-nakshatra-pada", "basic", "What is the Moon's nakshatra and pada?", (p["Moon"].nakshatra, str(p["Moon"].nakshatra_pada)))
    add("moon-pada", "basic", "Which pada is my Moon in?", (str(p["Moon"].nakshatra_pada), p["Moon"].nakshatra))
    add("jupiter-d1", "placement", "Where is Jupiter placed in my D1 chart?", ("Jupiter", p["Jupiter"].sign, str(p["Jupiter"].house), "D1"))
    add("mars-house", "placement", "Which house contains Mars in D1?", ("Mars", p["Mars"].sign, str(p["Mars"].house), "D1"))
    add("venus-sign", "placement", "What sign is Venus in in D1?", ("Venus", p["Venus"].sign, "D1"))
    add("second-house-occupants", "placement", "Which planets occupy the second house in D1?", ("D1", "second house", *occupants_d1))
    add("seventh-lord", "lordship", "Who rules the seventh house in D1?", ("seventh house", _ruler(chart, 7), "D1"))
    add("tenth-lord-placement", "lordship", "Where is the tenth-house lord placed in D1?", (tenth_lord, tenth_lord_position.sign, str(tenth_lord_position.house), "D1"))
    add("jupiter-lordships", "lordship", "Which D1 houses does Jupiter rule?", ("Jupiter", *(_houses_ruled(chart, "Jupiter")), "D1"))
    add("jupiter-d9", "divisional", "Where is Jupiter placed in D9 (Navamsa)?", ("Jupiter", p["Jupiter"].d9_sign, str(p["Jupiter"].d9_house), "D9"), division="D9")
    add("d10-ascendant", "divisional", "What is my D10 ascendant sign?", ("D10", chart.result.d10.ascendant_sign), division="D10")
    add("d10-tenth-occupants", "divisional", "Which planets occupy the tenth house of D10?", ("D10", "tenth house", *occupants_d10_10), division="D10")
    add("d1-d9-compare", "divisional", "Compare Jupiter's D1 and D9 sign and house placements.", ("Jupiter", p["Jupiter"].sign, str(p["Jupiter"].house), p["Jupiter"].d9_sign, str(p["Jupiter"].d9_house), "D1", "D9"), division="D9")
    add("current-dasha", "dasha", "Which Mahadasha and Antardasha are active now?", (chart.result.current_mahadasha.lord, dasha.lord))
    add("antardasha-end", "dasha", "When does my current Antardasha end?", (dasha.lord,), (dasha.end_date.isoformat(),))
    add("pratyantardasha-dates", "dasha", "What are the start and end dates of my current Pratyantardasha?", (praty.lord,), (praty.start_date.isoformat(), praty.end_date.isoformat()))
    add("jupiter-career", "interpretation", "What career themes could my Jupiter placement in D1 suggest?", ("Jupiter", p["Jupiter"].sign, str(p["Jupiter"].house), "D1", "career"))
    add("fifth-tenth-link", "interpretation", "How do the fifth and tenth house rulers relate in my D1 chart?", (house5_lord, house10_lord, "fifth", "tenth", "D1"))
    add("yoga-condition", "interpretation", "Does my chart meet the coded Budha-Aditya same-sign condition?", ("Budha-Aditya", present))
    add("exact-job-date", "unanswerable", "What exact date will I get a job?", (), (), missing=True)
    add("uranus", "unanswerable", "Where is Uranus placed in my chart?", (), (), missing=True)
    add("exact-salary", "unanswerable", "What exact salary will I earn from this chart?", (), (), missing=True)
    add("unsupported-d9-planet", "unanswerable", "What is Pluto's D9 house placement?", (), (), division="D9", missing=True)
    return cases


CHARTS = synthetic_charts()
CASES = tuple(case for chart in CHARTS for case in _build_cases(chart))


def selected_cases(smoke: bool = False) -> list[EvalCase]:
    if not smoke:
        return list(CASES)
    wanted = (
        "synthetic-a-ascendant", "synthetic-a-jupiter-d9", "synthetic-b-tenth-lord-placement",
        "synthetic-b-current-dasha", "synthetic-c-yoga-condition", "synthetic-c-uranus",
    )
    by_id = {case.case_id: case for case in CASES}
    return [by_id[key] for key in wanted]
