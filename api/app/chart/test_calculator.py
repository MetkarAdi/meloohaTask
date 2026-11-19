from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from api.app.chart.calculator import calculate_chart
from api.app.chart.models import ChartRequest


def test_user_birth_chart_matches_expected_vedic_placements_and_dasha():
    request = ChartRequest(
        birth_date=date(2003, 12, 3),
        birth_time=time(6, 43),
        location="Dhule, Maharashtra, India",
        latitude=20.9042,
        longitude=74.7749,
    )

    chart = calculate_chart(
        request,
        as_of=datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    by_name = {planet.name: planet for planet in chart.planets}
    assert chart.timezone == "Asia/Kolkata"
    assert chart.lagna_sign == "Scorpio"
    assert len(chart.planets) == 9
    assert (by_name["Sun"].sign, by_name["Sun"].house) == ("Scorpio", 1)
    assert (by_name["Jupiter"].sign, by_name["Jupiter"].house) == ("Leo", 10)
    assert (by_name["Mercury"].sign, by_name["Mercury"].house) == ("Sagittarius", 2)
    assert (by_name["Venus"].sign, by_name["Venus"].house) == ("Sagittarius", 2)
    assert (by_name["Ketu"].sign, by_name["Ketu"].house) == ("Libra", 12)

    assert chart.current_mahadasha.lord == "Ketu"
    assert chart.current_antardasha.lord == "Venus"
    assert chart.current_antardasha.end_date.year == 2027
    assert date(2027, 2, 1) <= chart.current_antardasha.end_date <= date(2027, 3, 31)
    assert len(chart.transits) == 2
    assert {transit.planet for transit in chart.transits} == {"Jupiter", "Saturn"}

    assert chart.facts[0] == "F001 : Lagna is Scorpio"
    assert any(fact.startswith("F006 : Jupiter in house 10 (Leo)") for fact in chart.facts)
