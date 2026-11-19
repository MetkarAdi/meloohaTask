"""Deterministic topic routing and grounded interpretation selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)
SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}
HOUSE_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth")
POSITION_RE = re.compile(
    r"^\s*(?:F\d{3})\s*:\s*(Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu)"
    r" in house (\d{1,2}) \((Aries|Taurus|Gemini|Cancer|Leo|Virgo|Libra|Scorpio|"
    r"Sagittarius|Capricorn|Aquarius|Pisces)\)", re.IGNORECASE
)
LAGNA_RE = re.compile(r"^\s*F\d{3}\s*:\s*Lagna is (" + "|".join(SIGNS) + r")\b", re.I)
TIMING_RE = re.compile(
    r"\b(when|timing|date|period|currently|current|today|now|this year|this month|"
    r"soon|future|dasha|forecast|time window)\b",
    re.I,
)


@dataclass(frozen=True)
class Interpretation:
    id: str
    key: str
    term: str
    text: str
    kind: str

    @property
    def fact(self) -> str:
        return f"{self.id} : {self.text}"


@lru_cache(maxsize=1)
def interpretations() -> tuple[Interpretation, ...]:
    path = Path(__file__).with_name("interpretations.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Interpretation(item["id"], item["key"], item["term"], item["text"], kind)
        for kind, entries in data.items()
        for item in entries
    )


def detect_topic(question: str) -> str:
    text = question.casefold()
    if re.search(r"\b(job|career|work|employment|profession|promotion|interview|workplace|boss)\b|नौकरी|करियर|काम", text):
        return "career"
    if re.search(r"\b(relationships?|love|romance|marriage|married|partners?|dating|spouse|breakup)\b|रिश्ता|प्रेम|विवाह|शादी", text):
        return "relationships"
    if re.search(r"\b(money|finances?|financial|wealth|income|salary|savings|debt|business|wealthy)\b|पैसा|धन|आय", text):
        return "money"
    if re.search(r"\b(home|house|family|property|mother|father)\b|घर|परिवार|मकान", text):
        return "home"
    if re.search(r"\b(education|school|study|studies|children|child|kids|creativity)\b|शिक्षा|पढ़ाई|बच्चे|संतान", text):
        return "education"
    if re.search(r"\b(health|illness|sick|medical|disease|wellbeing|well-being)\b|स्वास्थ्य|सेहत|बीमारी", text):
        return "health"
    return "general"


def target_houses_for_question(question: str) -> list[int]:
    """Return the topic houses shared by fact selection and chart highlights."""
    return {
        "career": [10],
        "relationships": [7],
        "money": [2, 11],
        "home": [4],
        "education": [5],
        "health": [1, 6, 8, 12],
        "general": [1, 5, 9],
    }[detect_topic(question)]


def route_question(question: str, chart_facts: Sequence[str]) -> list[str]:
    """Choose chart facts and interpretation facts deterministically for one question."""
    topic = detect_topic(question)
    timing = topic == "career" or bool(TIMING_RE.search(question))
    target_houses = set(target_houses_for_question(question))
    explicit_house = re.search(r"\b(?:house\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)\s+house|(" + "|".join(HOUSE_ORDINALS) + r")\s+house)\b", question, re.I)
    if explicit_house:
        number = int(explicit_house.group(1) or explicit_house.group(2) or (HOUSE_ORDINALS.index(explicit_house.group(3).casefold()) + 1))
        if 1 <= number <= 12:
            target_houses.add(number)

    lagna = next((match.group(1).title() for fact in chart_facts if (match := LAGNA_RE.match(fact))), None)
    positions: dict[str, tuple[int, str, str]] = {}
    transits: list[str] = []
    dasha_facts: list[str] = []
    for fact in chart_facts:
        if fact.startswith("F") and fact.split(":", 1)[-1].strip().startswith("Transiting "):
            transits.append(fact)
        if any(term in fact.casefold() for term in ("current mahadasha", "current antardasha", "current pratyantardasha")):
            dasha_facts.append(fact)
        match = POSITION_RE.match(fact)
        if match:
            positions[match.group(1).title()] = (int(match.group(2)), match.group(3).title(), fact)

    selected: list[str] = []

    def add(fact: str | None) -> None:
        if fact and fact not in selected:
            selected.append(fact)

    for fact in chart_facts:
        if LAGNA_RE.match(fact):
            add(fact)

    next_id = max((int(match.group(1)) for fact in chart_facts if (match := re.match(r"F(\d{3})\s*:", fact))), default=0) + 1
    derived_by_house: dict[int, list[str]] = {}
    if lagna:
        lagna_index = SIGNS.index(lagna)
        for house in sorted(target_houses):
            sign = SIGNS[(lagna_index + house - 1) % 12]
            stored = [fact for fact in chart_facts if re.search(rf"\bD1 house {house} sign is {sign}; ruler is {SIGN_LORDS[sign]}\b", fact, re.I)]
            derived = stored or [
                f"F{next_id:03d} : Sign on house {house} is {sign}",
                f"F{next_id + 1:03d} : Ruler of house {house} is {SIGN_LORDS[sign]}",
            ]
            if not stored:
                next_id += 2
            derived_by_house[house] = derived
            for fact in derived:
                add(fact)

    relevant_planets: set[str]
    if topic == "career":
        relevant_planets = {SIGN_LORDS[SIGNS[(SIGNS.index(lagna) + 9) % 12]]} if lagna else set()
        relevant_planets.add("Jupiter")
        relevant_planets.add("Saturn")
        relevant_planets.add("Sun")
    elif topic == "relationships":
        relevant_planets = {"Venus", "Moon", "Jupiter"}
    elif topic == "money":
        relevant_planets = {"Jupiter", "Mercury", "Venus"}
    elif topic == "home":
        relevant_planets = {"Moon", "Venus", "Mars"}
    elif topic == "education":
        relevant_planets = {"Jupiter", "Mercury", "Sun"}
    elif topic == "health":
        relevant_planets = {"Sun", "Moon", "Mars", "Saturn"}
    else:
        relevant_planets = {"Sun", "Moon", "Jupiter", "Venus"}
    # A directly named planet is always relevant, including follow-up questions
    # that do not use one of the broad topic keywords.
    relevant_planets.update(
        planet for planet in PLANETS if re.search(rf"\b{planet}\b", question, re.I)
    )

    relevant_lords = {
        (fact.rsplit(" ", 1)[-1] if "Ruler of house" in fact else re.search(r"ruler is\s+(\w+)", fact, re.I).group(1))
        for house in target_houses
        for fact in derived_by_house.get(house, [])
        if "Ruler of house" in fact or re.search(r"ruler is\s+\w+", fact, re.I)
    }
    relevant_planets.update(relevant_lords)
    for name, (house, _sign, fact) in positions.items():
        if house in target_houses or name in relevant_planets:
            add(fact)
    if topic in {"career", "money", "general"} or timing:
        for fact in transits:
            add(fact)
    if timing or topic in {"career", "general"}:
        for fact in dasha_facts:
            add(fact)

    house_keys = {str(house) for house in target_houses}
    planet_keys = set(relevant_planets)
    sign_keys: set[str] = set()
    for fact in selected:
        match = POSITION_RE.match(fact)
        if match:
            planet_keys.add(match.group(1).title())
            sign_keys.add(match.group(3).title())
        for sign in SIGNS:
            if re.search(rf"\b{sign}\b", fact, re.I):
                sign_keys.add(sign)

    lowered_question = question.casefold()
    if re.search(r"\b(?:d9|navamsa|navamsha)\b", lowered_question):
        for fact in chart_facts:
            if re.match(r"\s*F\d{3}\s*:\s*D9\b", fact, re.I):
                add(fact)
    if re.search(r"\b(?:d10|dasamsa|dashamsha|dashamsa)\b", lowered_question):
        for fact in chart_facts:
            if re.match(r"\s*F\d{3}\s*:\s*D10\b", fact, re.I):
                add(fact)
    if re.search(r"\b(?:lord|ruler|rules|governs)\b", lowered_question):
        for fact in chart_facts:
            if re.search(r"\bD1 house \d+ sign is .*; ruler is", fact, re.I):
                add(fact)
    if "yoga" in lowered_question:
        for fact in chart_facts:
            if "yoga" in fact.casefold():
                add(fact)

    requested_concepts = {"lagna", "house ruler"}
    if transits and any(fact in selected for fact in transits):
        requested_concepts.add("transit")
    if dasha_facts and any(fact in selected for fact in dasha_facts):
        requested_concepts.update({"mahadasha", "antardasha", "pratyantardasha", "timing limitation"})
    interpretations_by_key = {(item.kind, item.key.casefold()): item for item in interpretations()}
    meaning_facts: list[str] = []
    for house in sorted(house_keys, key=int):
        item = interpretations_by_key.get(("houses", house))
        if item:
            meaning_facts.append(item.fact)
    for planet in sorted(planet_keys, key=lambda value: PLANETS.index(value) if value in PLANETS else 99):
        item = interpretations_by_key.get(("planets", planet.casefold()))
        if item:
            meaning_facts.append(item.fact)
    for sign in SIGNS:
        if sign in sign_keys:
            item = interpretations_by_key.get(("signs", sign.casefold()))
            if item:
                meaning_facts.append(item.fact)
    for concept in requested_concepts:
        item = interpretations_by_key.get(("concepts", concept.casefold()))
        if item:
            meaning_facts.append(item.fact)

    for fact in meaning_facts:
        add(fact)
    return selected
