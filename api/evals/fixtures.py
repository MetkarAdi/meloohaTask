"""Fixed synthetic charts and questions used by the evaluation runner."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TestChart:
    chart_id: str
    facts: tuple[str, ...]


CHARTS = (
    TestChart("synthetic-scorpio", (
        "F001 : Lagna is Scorpio",
        "F002 : Sun in house 1 (Scorpio), direct, nakshatra Anuradha",
        "F003 : Moon in house 9 (Cancer), direct, nakshatra Pushya",
        "F004 : Mars in house 12 (Libra), direct, nakshatra Swati",
        "F005 : Mercury in house 2 (Sagittarius), direct, nakshatra Mula",
        "F006 : Jupiter in house 10 (Leo), direct, nakshatra Purva Phalguni",
        "F007 : Venus in house 2 (Sagittarius), direct, nakshatra Mula",
        "F008 : Saturn in house 8 (Gemini), retrograde, nakshatra Ardra",
        "F009 : Rahu in house 6 (Aries), retrograde, nakshatra Ashwini",
        "F010 : Ketu in house 12 (Libra), retrograde, nakshatra Swati",
        "F011 : Current mahadasha is Ketu from 2025-07-30 to 2032-07-29",
        "F012 : Current antardasha is Venus from 2025-12-26 to 2027-02-25",
        "F013 : Current pratyantardasha is Saturn from 2026-09-25 to 2026-12-02",
        "F014 : Transiting Jupiter in house 10 (Leo), direct, nakshatra Magha",
        "F015 : Transiting Saturn in house 5 (Pisces), retrograde, nakshatra Uttara Bhadrapada",
    )),
    TestChart("synthetic-aries", (
        "F001 : Lagna is Aries",
        "F002 : Sun in house 10 (Capricorn), direct, nakshatra Shravana",
        "F003 : Moon in house 4 (Cancer), direct, nakshatra Pushya",
        "F004 : Mars in house 1 (Aries), direct, nakshatra Ashwini",
        "F005 : Mercury in house 9 (Sagittarius), direct, nakshatra Mula",
        "F006 : Jupiter in house 7 (Libra), direct, nakshatra Swati",
        "F007 : Venus in house 11 (Aquarius), direct, nakshatra Shatabhisha",
        "F008 : Saturn in house 12 (Pisces), retrograde, nakshatra Revati",
        "F009 : Rahu in house 3 (Gemini), retrograde, nakshatra Ardra",
        "F010 : Ketu in house 9 (Sagittarius), retrograde, nakshatra Mula",
        "F011 : Current mahadasha is Jupiter from 2023-04-11 to 2039-04-10",
        "F012 : Current antardasha is Mercury from 2025-06-20 to 2027-09-26",
        "F013 : Current pratyantardasha is Venus from 2026-08-15 to 2027-01-09",
        "F014 : Transiting Jupiter in house 9 (Sagittarius), direct, nakshatra Purva Ashadha",
        "F015 : Transiting Saturn in house 12 (Pisces), retrograde, nakshatra Uttara Bhadrapada",
    )),
    TestChart("synthetic-cancer", (
        "F001 : Lagna is Cancer",
        "F002 : Sun in house 6 (Sagittarius), direct, nakshatra Mula",
        "F003 : Moon in house 1 (Cancer), direct, nakshatra Pushya",
        "F004 : Mars in house 10 (Aries), direct, nakshatra Ashwini",
        "F005 : Mercury in house 5 (Scorpio), direct, nakshatra Anuradha",
        "F006 : Jupiter in house 2 (Leo), direct, nakshatra Magha",
        "F007 : Venus in house 7 (Capricorn), direct, nakshatra Shravana",
        "F008 : Saturn in house 8 (Aquarius), retrograde, nakshatra Shatabhisha",
        "F009 : Rahu in house 4 (Libra), retrograde, nakshatra Swati",
        "F010 : Ketu in house 10 (Aries), retrograde, nakshatra Ashwini",
        "F011 : Current mahadasha is Moon from 2024-02-01 to 2034-02-01",
        "F012 : Current antardasha is Mars from 2026-03-10 to 2027-01-05",
        "F013 : Current pratyantardasha is Jupiter from 2026-10-18 to 2026-12-14",
        "F014 : Transiting Jupiter in house 2 (Leo), direct, nakshatra Magha",
        "F015 : Transiting Saturn in house 9 (Pisces), retrograde, nakshatra Uttara Bhadrapada",
    )),
)


QUESTIONS = {
    "career": (
        "What career strengths can I build on?",
        "How might I approach a job search?",
        "What could help me make steady progress at work?",
        "What work themes stand out in my chart?",
        "How can I think about a promotion?",
        "What might support my professional growth?",
        "How could I handle responsibilities at work?",
        "What skills might be useful for my career?",
        "How might current transits relate to my work?",
        "What career themes should I reflect on this year?",
    ),
    "relationships": (
        "What relationship themes stand out for me?",
        "How might I approach building a lasting partnership?",
        "What could help me communicate better with a partner?",
        "What does my chart suggest about close relationships?",
        "How can I bring more balance to dating?",
        "What relationship strengths can I nurture?",
        "How might I approach commitment thoughtfully?",
        "What should I reflect on in a partnership?",
        "How could I build more harmony in my relationships?",
        "What relationship themes are active in my current periods?",
    ),
    "timing": (
        "What does my current dasha suggest about timing?",
        "What broad timing window is shown for career themes?",
        "How long does my current sub-period last?",
        "What timing themes may be relevant for relationships?",
        "When does my current antardasha end?",
        "What is the current pratyantardasha period?",
        "How should I understand the dates in my chart?",
        "What broad period am I in now?",
        "How might current transits add timing context?",
        "What does the next period suggest for work?",
    ),
}


def selected_cases(smoke: bool = False) -> list[tuple[TestChart, str, str]]:
    cases = [(chart, topic, question) for chart in CHARTS for topic, questions in QUESTIONS.items() for question in questions]
    if not smoke:
        return cases
    # Five cases span all three synthetic charts and all requested topic groups.
    return [cases[index] for index in (0, 40, 80, 10, 50)]
