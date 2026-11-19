"""Run a small fixed prompt set and summarize provider/checker pass rates.

Run from the api directory with: python -m scripts.pass_rate
Configured Groq/Gemini keys are read from the process environment by the provider code.
"""

from collections import Counter

from app.llm.groq import generate_answer
from app.llm.routing import route_question


TEST_CHART = [
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
]

QUESTIONS = (
    "When might my career gain momentum?",
    "What relationship themes stand out?",
    "How could I approach money more thoughtfully?",
    "What strengths can I lean on?",
    "What does Saturn in my chart suggest?",
    "What might the current dasha period mean?",
    "How could I think about work this year?",
    "What does Venus suggest about connection?",
    "What themes might support learning?",
    "How might I reflect on upcoming changes?",
)


def main() -> None:
    counts: Counter[str] = Counter()
    for index, question in enumerate(QUESTIONS, start=1):
        facts = route_question(question, TEST_CHART)
        result = generate_answer(question, facts, stream=False)
        if result.provider == "fallback":
            bucket = "fallback"
        elif result.provider == "gemini":
            bucket = "gemini"
        elif result.validation_stage == "regenerated":
            bucket = "regenerated"
        else:
            bucket = "first_try"
        counts[bucket] += 1
        print(f"{index:02d}. {bucket}: {question}")

    print("\nAnswer pass summary (10 questions)")
    print(f"Passed on first try: {counts['first_try']}")
    print(f"Passed after one regenerate: {counts['regenerated']}")
    print(f"Passed via Gemini: {counts['gemini']}")
    print(f"Ended in grounded fallback: {counts['fallback']}")


if __name__ == "__main__":
    main()
