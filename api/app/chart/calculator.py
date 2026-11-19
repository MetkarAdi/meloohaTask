from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from geopy.geocoders import Nominatim
from kerykeion import AstrologicalSubjectFactory

from .models import ChartRequest, ChartResponse, DashaPeriod, DivisionalChart, DivisionalPlanet, PlanetPosition, TransitPosition

SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)
SIGN_NAMES = {
    "Ari": "Aries", "Tau": "Taurus", "Gem": "Gemini", "Can": "Cancer",
    "Leo": "Leo", "Vir": "Virgo", "Lib": "Libra", "Sco": "Scorpio",
    "Sag": "Sagittarius", "Cap": "Capricorn", "Aqu": "Aquarius", "Pis": "Pisces",
}
PLANETS = (
    ("Sun", "sun"), ("Moon", "moon"), ("Mars", "mars"), ("Mercury", "mercury"),
    ("Jupiter", "jupiter"), ("Venus", "venus"), ("Saturn", "saturn"),
    ("Rahu", "true_north_lunar_node"), ("Ketu", "true_south_lunar_node"),
)
DASHA_ORDER = ("Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury")
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}
DASHA_TOTAL_YEARS = sum(DASHA_YEARS.values())
DAYS_PER_DASHA_YEAR = 365.25
NAKSHATRA_SPAN = 360 / 27
PADA_SPAN = NAKSHATRA_SPAN / 4


def _varga_sign(longitude: float, division: int) -> str:
    normalized = longitude % 360
    rasi = int(normalized // 30)
    part = min(division - 1, int((normalized % 30) / (30 / division)))
    if division == 9:
        offset = {0: 0, 1: 8, 2: 4}[rasi % 3]
        return SIGNS[(rasi + offset + part) % 12]
    if division == 10:
        start = rasi if rasi % 2 == 0 else (rasi + 8) % 12
        return SIGNS[(start + part) % 12]
    raise ValueError("Only D9 and D10 are supported")


def _nakshatra_pada(longitude: float) -> int:
    return min(4, int((longitude % NAKSHATRA_SPAN) / PADA_SPAN) + 1)


@lru_cache(maxsize=256)
def _geocode(location: str) -> tuple[float, float]:
    """Resolve a birthplace through OpenStreetMap's Nominatim service."""
    geocoder = Nominatim(user_agent="melooha-vedic-chart/1.0 (birth-chart calculator)", timeout=10)
    result = geocoder.geocode(location, exactly_one=True)
    if result is None:
        raise ValueError(f"Could not find birthplace: {location}")
    return float(result.latitude), float(result.longitude)


def _sign_name(abbreviation: str) -> str:
    if abbreviation not in SIGN_NAMES:
        raise ValueError(f"Kerykeion returned an unknown sign: {abbreviation}")
    return SIGN_NAMES[abbreviation]


def _house(sign: str, lagna_sign: str) -> int:
    return (SIGNS.index(sign) - SIGNS.index(lagna_sign)) % 12 + 1


def _lord_at_birth(moon_longitude: float) -> tuple[str, float]:
    nakshatra_number = int(moon_longitude % 360 // NAKSHATRA_SPAN)
    within_nakshatra = (moon_longitude % NAKSHATRA_SPAN) / NAKSHATRA_SPAN
    return DASHA_ORDER[nakshatra_number % 9], within_nakshatra


def _period(lord: str, start: datetime, years: float) -> tuple[DashaPeriod, datetime]:
    end = start + timedelta(days=years * DAYS_PER_DASHA_YEAR)
    return DashaPeriod(lord=lord, start_date=start.date(), end_date=end.date()), end


def _current_nested_periods(moon_longitude: float, birth: datetime, as_of: datetime):
    first_lord, elapsed_fraction = _lord_at_birth(moon_longitude)
    lord_index = DASHA_ORDER.index(first_lord)
    mahadasha_start = birth - timedelta(
        days=elapsed_fraction * DASHA_YEARS[first_lord] * DAYS_PER_DASHA_YEAR
    )

    for offset in range(9):
        maha_lord = DASHA_ORDER[(lord_index + offset) % 9]
        maha, maha_end = _period(maha_lord, mahadasha_start, DASHA_YEARS[maha_lord])
        if mahadasha_start <= as_of < maha_end:
            sub_index = DASHA_ORDER.index(maha_lord)
            sub_start = mahadasha_start
            for sub_offset in range(9):
                sub_lord = DASHA_ORDER[(sub_index + sub_offset) % 9]
                sub_years = DASHA_YEARS[maha_lord] * DASHA_YEARS[sub_lord] / DASHA_TOTAL_YEARS
                sub, sub_end = _period(sub_lord, sub_start, sub_years)
                if sub_start <= as_of < sub_end:
                    pratyantar_index = DASHA_ORDER.index(sub_lord)
                    pratyantar_start = sub_start
                    for pratyantar_offset in range(9):
                        pratyantar_lord = DASHA_ORDER[(pratyantar_index + pratyantar_offset) % 9]
                        pratyantar_years = sub_years * DASHA_YEARS[pratyantar_lord] / DASHA_TOTAL_YEARS
                        pratyantar, pratyantar_end = _period(pratyantar_lord, pratyantar_start, pratyantar_years)
                        if pratyantar_start <= as_of < pratyantar_end:
                            return maha, sub, pratyantar
                        pratyantar_start = pratyantar_end
                    raise ValueError("Could not determine current pratyantardasha")
                sub_start = sub_end
            raise ValueError("Could not determine current antardasha")
        mahadasha_start = maha_end
    raise ValueError("Could not determine current Vimshottari mahadasha")


def _build_subject(name: str, moment: datetime, location: str, latitude: float, longitude: float):
    return AstrologicalSubjectFactory.from_birth_data(
        name=name,
        year=moment.year, month=moment.month, day=moment.day,
        hour=moment.hour, minute=moment.minute,
        lng=longitude, lat=latitude, tz_str=moment.tzinfo.key,
        online=False,
        zodiac_type="Sidereal", sidereal_mode="LAHIRI",
        houses_system_identifier="W", calculate_nakshatra=True,
        active_points=[
            "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
            "True_North_Lunar_Node", "True_South_Lunar_Node", "Ascendant",
        ],
    )


def calculate_chart(request: ChartRequest, as_of: datetime | None = None) -> ChartResponse:
    """Calculate a Lahiri sidereal whole-sign natal chart and current periods/transits."""
    latitude, longitude = (
        (request.latitude, request.longitude)
        if request.latitude is not None and request.longitude is not None
        else _geocode(request.location)
    )
    local_zone = ZoneInfo(request.timezone)
    local_birth = datetime.combine(request.birth_date, time(request.birth_time.hour, request.birth_time.minute), tzinfo=local_zone)
    now_local = (as_of or datetime.now(local_zone)).astimezone(local_zone)

    natal = _build_subject("Melooha Chart", local_birth, request.location, latitude, longitude)
    lagna = _sign_name(natal.ascendant.sign)
    d9_lagna = _varga_sign(natal.ascendant.abs_pos, 9)
    d10_lagna = _varga_sign(natal.ascendant.abs_pos, 10)
    planets: list[PlanetPosition] = []
    for name, attribute in PLANETS:
        point = getattr(natal, attribute)
        sign = _sign_name(point.sign)
        d9_sign = _varga_sign(point.abs_pos, 9)
        d10_sign = _varga_sign(point.abs_pos, 10)
        planets.append(PlanetPosition(
            name=name,
            sign=sign,
            house=_house(sign, lagna),
            retrograde=bool(point.retrograde),
            nakshatra=point.nakshatra or "",
            nakshatra_pada=_nakshatra_pada(point.abs_pos),
            d9_sign=d9_sign,
            d9_house=_house(d9_sign, d9_lagna),
            d10_sign=d10_sign,
            d10_house=_house(d10_sign, d10_lagna),
        ))
    d9 = DivisionalChart(
        ascendant_sign=d9_lagna,
        planets=[DivisionalPlanet(name=p.name, sign=p.d9_sign, house=p.d9_house) for p in planets],
    )
    d10 = DivisionalChart(
        ascendant_sign=d10_lagna,
        planets=[DivisionalPlanet(name=p.name, sign=p.d10_sign, house=p.d10_house) for p in planets],
    )

    mahadasha, antardasha, pratyantardasha = _current_nested_periods(
        natal.moon.abs_pos, local_birth, now_local
    )

    transit_options = {
        "name": "Current Transits", "lng": longitude, "lat": latitude,
        "tz_str": request.timezone, "online": False,
        "zodiac_type": "Sidereal", "sidereal_mode": "LAHIRI",
        "houses_system_identifier": "W", "calculate_nakshatra": True,
        "active_points": ["Jupiter", "Saturn"],
    }
    if as_of is None:
        transit_subject = AstrologicalSubjectFactory.from_current_time(**transit_options)
    else:
        transit_subject = AstrologicalSubjectFactory.from_birth_data(
            **transit_options,
            year=now_local.year, month=now_local.month, day=now_local.day,
            hour=now_local.hour, minute=now_local.minute,
        )
    transits = []
    for name, attribute in (("Jupiter", "jupiter"), ("Saturn", "saturn")):
        point = getattr(transit_subject, attribute)
        sign = _sign_name(point.sign)
        transits.append(TransitPosition(
            planet=name, sign=sign, house=_house(sign, lagna),
            retrograde=bool(point.retrograde), nakshatra=point.nakshatra or "",
        ))

    facts: list[str] = []

    def add_fact(text: str) -> None:
        facts.append(f"F{len(facts) + 1:03d} : {text}")

    add_fact(f"Lagna is {lagna}")
    for planet in planets:
        retrograde = "retrograde" if planet.retrograde else "direct"
        add_fact(f"{planet.name} in house {planet.house} ({planet.sign}), {retrograde}, nakshatra {planet.nakshatra}, pada {planet.nakshatra_pada}")
    add_fact(f"Current mahadasha is {mahadasha.lord} from {mahadasha.start_date} to {mahadasha.end_date}")
    add_fact(f"Current antardasha is {antardasha.lord} from {antardasha.start_date} to {antardasha.end_date}")
    add_fact(f"Current pratyantardasha is {pratyantardasha.lord} from {pratyantardasha.start_date} to {pratyantardasha.end_date}")
    for transit in transits:
        retrograde = "retrograde" if transit.retrograde else "direct"
        add_fact(f"Transiting {transit.planet} in house {transit.house} ({transit.sign}), {retrograde}, nakshatra {transit.nakshatra}")

    for house in range(1, 13):
        house_sign = SIGNS[(SIGNS.index(lagna) + house - 1) % 12]
        house_lord = {
            "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
            "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
            "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
        }[house_sign]
        add_fact(f"D1 house {house} sign is {house_sign}; ruler is {house_lord}")
    add_fact(f"D9 ascendant is {d9.ascendant_sign}")
    for planet in d9.planets:
        add_fact(f"D9 {planet.name} in house {planet.house} ({planet.sign})")
    add_fact(f"D10 ascendant is {d10.ascendant_sign}")
    for planet in d10.planets:
        add_fact(f"D10 {planet.name} in house {planet.house} ({planet.sign})")
    by_planet = {p.name: p for p in planets}
    budha_aditya_present = by_planet["Sun"].sign == by_planet["Mercury"].sign
    yoga_status = "present" if budha_aditya_present else "not present"
    add_fact(f"Budha-Aditya Yoga same-sign condition is {yoga_status} (Sun {by_planet['Sun'].sign}; Mercury {by_planet['Mercury'].sign})")

    return ChartResponse(
        birth_date=request.birth_date,
        birth_time=request.birth_time,
        timezone=request.timezone,
        location=request.location,
        lagna_sign=lagna,
        planets=planets,
        current_mahadasha=mahadasha,
        current_antardasha=antardasha,
        current_pratyantardasha=pratyantardasha,
        transits=transits,
        d9=d9,
        d10=d10,
        facts=facts,
    )
