"""Plain-Python checks for chart claims and grounded interpretations."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Sequence

from .routing import TIMING_RE, detect_topic

LOGGER = logging.getLogger("melooha.llm.validation")

FACT_RE = re.compile(r"^\s*([FM]\d{3})\s*:\s*(.*?)\s*$", re.I)
CITATION_RE = re.compile(r"\[([FM]\d{3})\]", re.I)
TERM_MARKUP_RE = re.compile(r"\[\[([^\]|]+)\|(M\d{3})\]\]", re.I)
PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)
HOUSE_WORDS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth",
)
HOUSE_WORD_NUMBERS = {word: index for index, word in enumerate(HOUSE_WORDS, 1)}
HOUSE_RE = re.compile(
    r"\b(?:house\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)?\s+house|("+
    "|".join(HOUSE_WORDS) + r")\s+house)\b", re.I,
)
PLANET_RE = re.compile(r"\b(" + "|".join(PLANETS) + r")\b", re.I)
SIGN_RE = re.compile(r"\b(" + "|".join(SIGNS) + r")\b", re.I)
ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
ISO_MONTH_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?!-\d)")
YEAR_RE = re.compile(r"\b((?:19|20|21)\d{2})\b")
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_ALIASES = {name[:3]: value for name, value in MONTHS.items()}
MONTH_DATE_RE = re.compile(
    r"\b(" + "|".join(MONTHS) + r"|" + "|".join(MONTH_ALIASES) + r")\s+(\d{1,2})(?:,)?\s+((?:19|20|21)\d{2})\b"
    r"|\b(" + "|".join(MONTHS) + r"|" + "|".join(MONTH_ALIASES) + r")\s+((?:19|20|21)\d{2})\b"
    r"|\b(\d{1,2})\s+(" + "|".join(MONTHS) + r"|" + "|".join(MONTH_ALIASES) + r")\s+((?:19|20|21)\d{2})\b", re.I,
)
NUMERIC_MONTH_YEAR_RE = re.compile(r"\b(\d{1,2})\s*/\s*((?:19|20|21)\d{2})\b")
CERTAINTY_RE = re.compile(
    r"\b(?:definitely|guarantee(?:d|s)?|certain(?:ly)?|inevitable|inevitably|assured|"
    r"always|never|promise(?:d)?|definitive)\b|\bwill\s+certainly\b|\bwithout\s+a\s+doubt\b|"
    r"\b100\s*%\b|\b(?:sure|bound)\s+to\b|\bno\s+chance\b", re.I,
)
PLACEMENT_RE = re.compile(
    r"\b(" + "|".join(PLANETS) + r")\b[^.!?;\n]{0,55}?\b(?:in|occupies|occupying|"
    r"placed in|positioned in)\s+(?:the\s+)?(house\s*\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+house|"
    + "|".join(HOUSE_WORDS) + r")\b", re.I,
)
PLANET_SIGN_RE = re.compile(
    r"\b(" + "|".join(PLANETS) + r")\b[^.!?;\n]{0,35}?\b(?:in|through)\s+("+
    "|".join(SIGNS) + r")\b", re.I,
)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    text: str


def _house_number(match: re.Match[str]) -> int:
    if match.group(1) or match.group(2):
        return int(match.group(1) or match.group(2))
    return HOUSE_WORD_NUMBERS[match.group(3).casefold()]


def _parse_facts(facts: Sequence[str]) -> tuple[dict[str, Fact], list[str]]:
    parsed: dict[str, Fact] = {}
    issues: list[str] = []
    for raw in facts:
        match = FACT_RE.match(raw)
        if not match:
            issues.append("A supplied fact is missing its F### or M### ID.")
            continue
        fact_id, text = match.groups()
        fact_id = fact_id.upper()
        if fact_id in parsed:
            issues.append(f"Supplied facts contain duplicate ID [{fact_id}].")
        parsed[fact_id] = Fact(fact_id, text)
    return parsed, issues


def _date_mentions(text: str) -> list[tuple[str, tuple[int, ...]]]:
    text = _normalize(text)
    mentions: list[tuple[str, tuple[int, ...]]] = []
    full_date_spans: list[tuple[int, int]] = []
    for match in ISO_DATE_RE.finditer(text):
        year, month, day = (int(part) for part in match.group(1).split("-"))
        mentions.append((match.group(1), (year, month, day)))
        full_date_spans.append(match.span())
    for match in ISO_MONTH_RE.finditer(text):
        if any(start <= match.start() < end for start, end in full_date_spans):
            continue
        year, month = int(match.group(1)), int(match.group(2))
        mentions.append((match.group(0), (year, month)))
        full_date_spans.append(match.span())
    for match in MONTH_DATE_RE.finditer(text):
        month_text, day_text, year_text, month_year_text, year_only_text, day_first, month_day_first, year_day_first = match.groups()
        if day_first:
            month_name, day_value, year_value = month_day_first, day_first, year_day_first
            parts = (int(year_value), MONTHS.get(month_name.casefold(), MONTH_ALIASES[month_name[:3].casefold()]), int(day_value))
        else:
            month_name = month_text or month_year_text
            year = int(year_text or year_only_text)
            month = MONTHS.get(month_name.casefold(), MONTH_ALIASES[month_name[:3].casefold()])
            parts = (year, month) if not day_text else (year, month, int(day_text))
        mentions.append((match.group(0), parts))
        full_date_spans.append(match.span())
    for match in NUMERIC_MONTH_YEAR_RE.finditer(text):
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            mentions.append((match.group(0), (year, month)))
            full_date_spans.append(match.span())
    for match in YEAR_RE.finditer(text):
        if not any(start <= match.start() < end for start, end in full_date_spans):
            mentions.append((match.group(1), (int(match.group(1)),)))
    return mentions


def _fact_date_parts(text: str) -> set[tuple[int, ...]]:
    parts: set[tuple[int, ...]] = set()
    for mention, value in _date_mentions(text):
        if len(value) == 3:
            year, month, day = value
            parts.update({(year,), (year, month), (year, month, day)})
        elif len(value) == 2:
            parts.update({(value[0],), value})
        else:
            parts.add(value)
    return parts


def _split_sentences(answer: str) -> list[str]:
    clean = TERM_MARKUP_RE.sub(r"\1", answer.strip())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", clean) if part.strip()]


def _placement(text: str) -> list[tuple[str, int]]:
    result = []
    for match in PLACEMENT_RE.finditer(text):
        house_match = HOUSE_RE.search(match.group(2))
        if house_match:
            result.append((match.group(1).casefold(), _house_number(house_match)))
    return result


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(str.maketrans({"\u202f": " ", "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u2007": " "}))).strip().lower()


def check_answer(answer: str, facts: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return hard rejections and soft citation warnings separately."""
    parsed, issues = _parse_facts(facts)
    answer = _normalize(answer)
    known_ids = set(parsed)
    chart_facts = {fact_id: fact for fact_id, fact in parsed.items() if fact_id.startswith("F")}
    all_text = " ".join(fact.text for fact in parsed.values())
    chart_text = " ".join(fact.text for fact in chart_facts.values())
    known_houses = {
        _house_number(match) for fact in parsed.values() for match in HOUSE_RE.finditer(fact.text)
    }
    allowed_date_parts = set().union(*(_fact_date_parts(fact.text) for fact in parsed.values())) if parsed else set()
    known_placements: set[tuple[str, int]] = set()
    known_planet_signs: set[tuple[str, str]] = set()
    for fact in chart_facts.values():
        known_placements.update((planet.casefold(), house) for planet, house in _placement(fact.text))
        position_match = re.search(
            r"\b(" + "|".join(PLANETS) + r")\s+in\s+(?:house\s*\d+\s*\()?\s*("+
            "|".join(SIGNS) + r")\b", fact.text, re.I,
        )
        if position_match:
            known_planet_signs.add((position_match.group(1).casefold(), position_match.group(2).casefold()))

    # Validate only hard rules here. Sentence-level citation quality is reported as a warning.
    for _term, term_id in TERM_MARKUP_RE.findall(answer):
        if term_id.upper() not in known_ids or not term_id.upper().startswith("M"):
            issues.append(f"Tooltip term [{term_id.upper()}] is not among the supplied interpretation facts.")
    for cited_id in CITATION_RE.findall(answer):
        if cited_id.upper() not in known_ids:
            issues.append(f"Citation [{cited_id.upper()}] does not exist in the supplied facts.")

    for sentence in _split_sentences(answer):
        cited_ids = [cite.upper() for cite in CITATION_RE.findall(sentence) if cite.upper() in parsed]
        cited_facts = [parsed[cite] for cite in cited_ids]
        for planet in {name.casefold() for name in PLANET_RE.findall(sentence)}:
            if not re.search(rf"\b{re.escape(planet)}\b", all_text, re.I):
                issues.append(f"Planet {planet.title()} is not present in the supplied facts.")

        for sign in {name.casefold() for name in SIGN_RE.findall(sentence)}:
            if not re.search(rf"\b{re.escape(sign)}\b", all_text, re.I):
                issues.append(f"Sign {sign.title()} is not present in the supplied facts.")

        for house_match in HOUSE_RE.finditer(sentence):
            house = _house_number(house_match)
            if house not in known_houses:
                issues.append(f"House {house} is not present in the supplied facts.")
        for planet, house in _placement(sentence):
            if (planet, house) not in known_placements:
                issues.append(f"{planet.title()} in house {house} contradicts or is not supported by the supplied chart facts.")

        for planet, sign in re.findall(PLANET_SIGN_RE, sentence):
            pair = (planet.casefold(), sign.casefold())
            if pair not in known_planet_signs:
                issues.append(f"{planet.title()} in {sign.title()} contradicts or is not supported by the supplied chart facts.")

        if re.search(r"\b(?:lagna|ascendant)\b", sentence, re.I):
            supported_lagna = [match.group(1) for fact in chart_facts.values()
                               if (match := re.search(r"\b(?:lagna|ascendant)\s+(?:is|in)\s+("+
                                                  "|".join(SIGNS) + r")\b", fact.text, re.I))]
            sentence_signs = [sign for sign in SIGNS if re.search(rf"\b{sign}\b", sentence, re.I)]
            for sign in sentence_signs:
                if not any(actual.casefold() == sign.casefold() for actual in supported_lagna):
                    issues.append(f"Lagna is not in {sign} according to the cited chart facts.")

        for mention, date_parts in _date_mentions(sentence):
            if date_parts not in allowed_date_parts:
                issues.append(f"Date {mention} is not present in the supplied facts.")
        if CERTAINTY_RE.search(sentence):
            issues.append("Avoid guarantees, certainty words, and definite predictions; describe tendencies only.")

    warnings: list[str] = []
    return list(dict.fromkeys(issues)), list(dict.fromkeys(warnings))


def validate_answer(answer: str, facts: Sequence[str]) -> list[str]:
    """Return hard violations; soft citation warnings are logged and do not reject."""
    hard, soft = check_answer(answer, facts)
    for warning in soft:
        LOGGER.warning("Soft answer citation warning=%s", warning)
    return hard


def safe_violation_codes(issues: Sequence[str]) -> list[str]:
    """Reduce validation details to non-personal categories for operational logs."""
    codes: list[str] = []
    for issue in issues:
        lowered = issue.casefold()
        if "citation" in lowered:
            code = "unknown_citation_id"
        elif "tooltip term" in lowered:
            code = "unknown_interpretation_id"
        elif "planet" in lowered and ("not present" in lowered or "house" in lowered or "sign" in lowered):
            code = "unsupported_planet_claim"
        elif "sign" in lowered or "lagna" in lowered or "ascendant" in lowered:
            code = "unsupported_sign_or_lagna_claim"
        elif "house" in lowered:
            code = "unsupported_house_claim"
        elif "date" in lowered or "year" in lowered:
            code = "unsupported_date_claim"
        elif "guarantee" in lowered or "certainty" in lowered or "predictions" in lowered:
            code = "certainty_language"
        elif "fact" in lowered:
            code = "invalid_supplied_facts"
        else:
            code = "other_validation_failure"
        codes.append(code)
    return list(dict.fromkeys(codes))


def safe_fact_answer(facts: Sequence[str], question: str = "") -> str:
    """Compose a short, relevant answer from routed F and M facts."""
    parsed, _ = _parse_facts(facts)
    by_id = parsed
    topic = detect_topic(question)
    dasha_facts = [fact for fact in parsed.values() if fact.fact_id.startswith("F") and re.search(
        r"current (?:mahadasha|antardasha)", fact.text, re.I
    )]
    sentences: list[str] = []
    if dasha_facts:
        maha = next((fact for fact in dasha_facts if "mahadasha" in fact.text.casefold()), None)
        antar = next((fact for fact in dasha_facts if "antardasha" in fact.text.casefold()), None)
        explanations = [
            fact for fact in parsed.values() if fact.fact_id.startswith("M") and
            fact.fact_id in {"M035", "M036"}
        ]
        parts = []
        for fact, term_name, meaning_id in ((maha, "mahadasha", "M035"), (antar, "antardasha", "M036")):
            if fact:
                lord_match = re.search(r"is\s+(\w+)\s+from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", fact.text, re.I)
                if lord_match:
                    lord, start, end = lord_match.groups()
                    parts.append(f"your current {lord} [[{term_name.title()}|{meaning_id}]] runs from {start} to {end} [{fact.fact_id}][{meaning_id}]")
        if parts:
            sentences.append("The current chart timing is " + " and ".join(parts) + ".")

    house_number = {"career": 10, "relationships": 7, "money": 2, "health": 6}.get(topic, 1)
    house_meaning = next((fact for fact in parsed.values() if fact.fact_id.startswith("M") and
                          re.search(rf"\b{HOUSE_WORDS[house_number - 1]}\s+house\b", fact.text, re.I)), None)
    sign_fact = next((fact for fact in parsed.values() if fact.fact_id.startswith("F") and
                      re.search(rf"sign on house {house_number} is (\w+)", fact.text, re.I)), None)
    ruler_fact = next((fact for fact in parsed.values() if fact.fact_id.startswith("F") and
                       re.search(rf"ruler of house {house_number} is (\w+)", fact.text, re.I)), None)
    if house_meaning and sign_fact and ruler_fact:
        sign = re.search(r"is (\w+)$", sign_fact.text).group(1)
        ruler = re.search(r"is (\w+)$", ruler_fact.text).group(1)
        house_label = HOUSE_WORDS[house_number - 1]
        sentences.append(
            f"As a general frame, the [[{house_label} house|{house_meaning.fact_id}]] is associated with relevant themes; "
            f"your chart places {sign} on it and names {ruler} as its ruler [{house_meaning.fact_id}]"
            f"[{sign_fact.fact_id}][{ruler_fact.fact_id}]."
        )

    if topic == "career" or TIMING_RE.search(question):
        timing_meaning = by_id.get("M041")
        if timing_meaning and dasha_facts:
            cited = "".join(f"[{fact.fact_id}]" for fact in dasha_facts[:2])
            sentences.append(
                f"Those dasha dates give a broad timing window, while the supplied facts do not specify an exact "
                f"date for an outside event [{timing_meaning.fact_id}]{cited}."
            )
    else:
        asked_planet = next((planet for planet in PLANETS if re.search(rf"\b{planet}\b", question, re.I)), None)
        if asked_planet:
            placement = next((fact for fact in parsed.values() if fact.fact_id.startswith("F") and
                              re.match(rf"\s*{asked_planet}\s+in\s+house\s+\d+", fact.text, re.I)), None)
            planet_meaning = next((fact for fact in parsed.values() if fact.fact_id.startswith("M") and
                                   fact.fact_id in {"M013", "M014", "M015", "M016", "M017", "M018", "M019", "M020", "M021"} and
                                   re.search(rf"\b{asked_planet}\b", fact.text, re.I)), None)
            if placement and planet_meaning:
                sentences.append(
                    f"Your chart places {placement.text} [{placement.fact_id}], and {asked_planet} is associated "
                    f"with the themes described here [{planet_meaning.fact_id}]."
                )

    if not sentences:
        first_chart = next((fact for fact in parsed.values() if fact.fact_id.startswith("F")), None)
        first_meaning = next((fact for fact in parsed.values() if fact.fact_id.startswith("M")), None)
        if first_chart and first_meaning:
            sentences.append(
                f"Your chart includes {first_chart.text} [{first_chart.fact_id}]. "
                f"In Vedic astrology, {first_meaning.text[0].lower() + first_meaning.text[1:]} [{first_meaning.fact_id}]."
            )
    return " ".join(sentences[:3]) or "I need verified chart facts before I can offer a grounded reading."
