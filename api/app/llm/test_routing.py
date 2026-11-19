from api.app.llm.routing import detect_topic, interpretations, route_question, target_houses_for_question
from api.app.llm.validation import safe_fact_answer, validate_answer


CHART_FACTS = [
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


def test_chart_highlights_match_fact_routing_topics():
    assert target_houses_for_question("When could I find a job?") == [10]
    assert target_houses_for_question("How are my relationships?") == [7]
    assert target_houses_for_question("Will money improve?") == [2, 11]


def test_interpretation_catalog_has_stable_ids_and_beginner_definitions():
    items = interpretations()
    ids = [item.id for item in items]
    assert len(ids) == len(set(ids))
    assert {item.kind for item in items} == {"houses", "planets", "signs", "concepts"}
    assert len([item for item in items if item.kind == "houses"]) == 12
    assert len([item for item in items if item.kind == "planets"]) == 9
    assert len([item for item in items if item.kind == "signs"]) == 12
    assert all(item.id.startswith("M") and 1 <= len(item.text.split(". ")) <= 2 for item in items)


def test_question_topic_detection_routes_career_facts_and_relevant_meanings():
    assert detect_topic("When will I get a job?") == "career"
    facts = route_question("When will I get a job?", CHART_FACTS)
    assert "F016 : Sign on house 10 is Leo" in facts
    assert "F017 : Ruler of house 10 is Sun" in facts
    assert "F006 : Jupiter in house 10 (Leo), direct, nakshatra Purva Phalguni" in facts
    assert "F014 : Transiting Jupiter in house 10 (Leo), direct, nakshatra Magha" in facts
    assert "F015 : Transiting Saturn in house 5 (Pisces), retrograde, nakshatra Uttara Bhadrapada" in facts
    assert "F011 : Current mahadasha is Ketu from 2025-07-30 to 2032-07-29" in facts
    assert "F012 : Current antardasha is Venus from 2025-12-26 to 2027-02-25" in facts
    assert any(item.startswith("M010 :") for item in facts)
    assert any(item.startswith("M041 :") for item in facts)
    assert not any(item.startswith("M007 :") for item in facts)


def test_relationship_routing_includes_seventh_house_venus_and_timing_when_asked():
    assert detect_topic("When might I meet a partner?") == "relationships"
    facts = route_question("When might I meet a partner?", CHART_FACTS)
    assert any("Sign on house 7" in item for item in facts)
    assert any("Ruler of house 7" in item for item in facts)
    assert "F007 : Venus in house 2 (Sagittarius), direct, nakshatra Mula" in facts
    assert "F011 : Current mahadasha is Ketu from 2025-07-30 to 2032-07-29" in facts
    assert any(item.startswith("M007 :") for item in facts)
    assert any(item.startswith("M018 :") for item in facts)


def test_money_health_and_general_topics_are_detected_without_an_llm():
    assert detect_topic("How can I improve my finances?") == "money"
    assert detect_topic("What does my wellbeing pattern look like?") == "health"
    assert detect_topic("What strengths can I lean on?") == "general"
    money = route_question("How can I improve my finances?", CHART_FACTS)
    assert any(item.startswith("M002 :") for item in money)
    assert any(item.startswith("M011 :") for item in money)
    health = route_question("What does my wellbeing pattern look like?", CHART_FACTS)
    assert any("Sign on house 6" in item for item in health)
    assert any(item.startswith("M006 :") for item in health)


def test_checker_accepts_explanations_and_definitions_but_rejects_wrong_placement():
    facts = route_question("When will I get a job?", CHART_FACTS)
    answer = (
        "Your current [[Ketu mahadasha|M035]] runs through 2032-07-29, while the "
        "[[Venus antardasha|M036]] runs through 2027-02-25 [F011][F012][M035][M036]. "
        "The [[tenth house|M010]] is associated with career and public work; in your chart "
        "Leo is on that house and Sun is its ruler [M010][F016][F017]."
    )
    assert validate_answer(answer, facts) == []

    wrong = "Saturn may indicate a career focus in house 10 (Leo) [F008][M010]."
    violations = validate_answer(wrong, facts)
    assert any("Saturn in house 10 contradicts" in issue for issue in violations)


def test_safe_fallback_is_relevant_cited_and_more_than_a_generic_template():
    facts = route_question("When will I get a job?", CHART_FACTS)
    fallback = safe_fact_answer(facts, "When will I get a job?")
    assert 2 <= fallback.count(".") <= 3
    assert "current Ketu" in fallback
    assert "2027-02-25" in fallback
    assert "tendency-based point for reflection" not in fallback
    assert validate_answer(fallback, facts) == []


def test_general_planet_followup_gets_its_placement_and_interpretation():
    facts = route_question("What does Saturn suggest?", CHART_FACTS)
    assert "F008 : Saturn in house 8 (Gemini), retrograde, nakshatra Ardra" in facts
    assert any(item.startswith("M019 :") for item in facts)
    fallback = safe_fact_answer(facts, "What does Saturn suggest?")
    assert "Saturn in house 8" in fallback
    assert validate_answer(fallback, facts) == []


def test_five_sentence_natural_answer_allows_uncited_connecting_sentences_and_unicode_date():
    facts = route_question("When might work improve?", CHART_FACTS)
    answer = (
        "Jupiter in house 10 (Leo) may highlight growth through visible work [F006][M017]. "
        "Career paths can also depend on choices and changing circumstances. "
        "That can make gradual experience useful. "
        "The current Venus antardasha runs through December\u202f2025 [F012][M036]. "
        "Taken together, those details suggest themes for reflection [F011][M035]."
    )
    assert validate_answer(answer, facts) == []


def test_answer_with_no_citations_is_accepted():
    facts = route_question("When might work improve?", CHART_FACTS)
    answer = (
        "Jupiter in house 10 (Leo) may support visibility in career matters. "
        "The current Venus antardasha runs through December 2025. "
        "These themes can be useful to consider while exploring opportunities."
    )
    assert validate_answer(answer, facts) == []


def test_wrong_house_and_unsupported_date_are_hard_rejections():
    facts = route_question("When might work improve?", CHART_FACTS)
    wrong_house = "Saturn is in house 2 [F008][M010]."
    assert any("Saturn in house 2 contradicts" in issue for issue in validate_answer(wrong_house, facts))
    wrong_date = "The relevant period may be December 2028 [F012][M036]."
    assert any("Date december 2028 is not present" in issue for issue in validate_answer(wrong_date, facts))


def test_date_parser_accepts_supported_common_formats():
    facts = ["F001 : Current antardasha is Venus from 2025-12-26 to 2027-02-25", "F002 : Example date is 2027-02-02", "M036 : Antardasha is a subperiod"]
    for date in ("December 2025", "Dec 2025", "2025-12", "12/2025", "2 February 2027"):
        assert validate_answer(f"This timing period includes {date} [F001][M036].", facts) == [], date
    assert any("2025-13" in issue for issue in validate_answer("This period is 2025-13 [F001][M036].", facts))
