"""Deterministic evaluation checks for expected chart claims and unsupported answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.llm.validation import check_answer, _date_mentions, PLACEMENT_RE, PLANET_SIGN_RE, HOUSE_RE, _house_number
from .fixtures import EvalCase

ACKNOWLEDGMENT_RE = re.compile(r"\b(?:not (?:available|provided|shown|specified|included|computed|in this chart)|does not (?:show|include|provide)|cannot determine|can't determine|cannot be determined|not enough information|unsupported|no reliable way to know|can't predict|cannot predict|no exact (?:date|salary)|not possible to know)\b", re.I)
PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
HOUSE_RE = re.compile(r"\b(?:house\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)\s+house|(" + "|".join(ORDINALS) + r")\s+house)\b", re.I)


@dataclass(frozen=True)
class DeterministicResult:
    passed: bool
    grounding_passed: bool
    violations: tuple[str, ...]
    missing_expected: tuple[str, ...]
    missing_acknowledgment: bool


def _contains_expected(answer: str, term: str) -> bool:
    if term.casefold() in {"d1", "d9", "d10"}:
        return re.search(rf"\b{re.escape(term)}\b", answer, re.I) is not None
    house_term = re.fullmatch(r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)\s+house", term, re.I)
    if house_term:
        n = ORDINALS[house_term.group(1).casefold()]
        suffix = "th" if n % 100 in {11, 12, 13} else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        ordinal_word = house_term.group(1)
        return bool(re.search(rf"\bhouse\s*{n}\b|\b{n}{suffix}\s+house\b|\b{ordinal_word}\s+house\b", answer, re.I))
    if term.isdigit() or term.casefold() in ORDINALS:
        n = int(term) if term.isdigit() else ORDINALS[term.casefold()]
        ordinal_word = ORDINALS and next((word for word, value in ORDINALS.items() if value == n), None)
        suffix = "th" if n % 100 in {11, 12, 13} else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return bool(re.search(rf"\b{n}(?:{suffix})?\b", answer, re.I) or (ordinal_word and re.search(rf"\b{ordinal_word}\b", answer, re.I)))
    return re.search(rf"\b{re.escape(term)}\b", answer, re.I) is not None


def _division_claim_issues(answer: str, facts: Sequence[str], case: EvalCase) -> list[str]:
    expected: dict[str, dict[str, tuple[int, str]]] = {division: {} for division in ("D1", "D9", "D10")}
    for raw in facts:
        text = re.sub(r"^\s*F\d{3}\s*:\s*", "", raw, flags=re.I)
        match = re.match(r"(?:(D9|D10)\s+)?(Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu)\s+in\s+house\s+(\d{1,2})\s+\(([^)]+)\)", text, re.I)
        if match:
            division, planet, house, sign = match.groups()
            expected[(division or "D1").upper()][planet.casefold()] = (int(house), sign.title())
    issues = []
    marker_re = re.compile(r"\b(D1|D9|D10|navamsa|navamsha|dasamsa|dashamsha|dashamsa)\b", re.I)
    def nearest_division(sentence: str, position: int) -> str | None:
        markers = [m for m in marker_re.finditer(sentence[:position]) if position - m.end() <= 60]
        if markers:
            value = markers[-1].group(1).casefold()
            return "D9" if value in {"d9", "navamsa", "navamsha"} else "D10" if value in {"d10", "dasamsa", "dashamsha", "dashamsa"} else "D1"
        all_markers = {m.group(1).casefold() for m in marker_re.finditer(sentence)}
        if len(all_markers) == 1:
            value = next(iter(all_markers))
            return "D9" if value in {"d9", "navamsa", "navamsha"} else "D10" if value in {"d10", "dasamsa", "dashamsha", "dashamsa"} else "D1"
        return case.division if case.division in {"D9", "D10"} else None
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        for claim in PLACEMENT_RE.finditer(sentence):
            planet = claim.group(1).casefold()
            division = nearest_division(sentence, claim.start())
            if division:
                want = expected[division].get(planet)
                house_match = HOUSE_RE.search(claim.group(0))
                claimed = _house_number(house_match) if house_match else None
                if want and claimed is not None and want[0] != claimed:
                    issues.append(f"{division} placement mismatch: {claim.group(1)} expected house {want[0]} ({want[1]}), found house {claimed}.")
        for claim in PLANET_SIGN_RE.finditer(sentence):
            planet = claim.group(1).casefold()
            division = nearest_division(sentence, claim.start())
            if division:
                want = expected[division].get(planet)
                sign = claim.group(2).title()
                if want and want[1] != sign:
                    issues.append(f"{division} sign mismatch: {claim.group(1)} expected {want[1]}, found {sign}.")
    return list(dict.fromkeys(issues))


def validate_eval_answer(answer: str, facts: Sequence[str], case: EvalCase) -> DeterministicResult:
    hard, _soft = check_answer(answer, facts)
    violations = list(hard) + _division_claim_issues(answer, facts, case)
    missing_expected = [term for term in case.required_terms if not _contains_expected(answer, term)]
    mentioned_dates = {tuple(parts) for _raw, parts in _date_mentions(answer)}
    for expected in case.required_dates:
        from datetime import date
        value = date.fromisoformat(expected)
        if (value.year, value.month, value.day) not in mentioned_dates:
            missing_expected.append(expected)
    missing_ack = case.acknowledge_missing and not ACKNOWLEDGMENT_RE.search(answer)
    if missing_ack:
        violations.append("Unanswerable request was not acknowledged as unsupported by the supplied chart.")
    passed = not violations and not missing_expected
    return DeterministicResult(passed, not violations, tuple(violations), tuple(missing_expected), missing_ack)
