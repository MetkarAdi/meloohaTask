from __future__ import annotations

import unicodedata
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/locations", tags=["locations"])
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
PHOTON_URL = "https://photon.komoot.io/api/"
REQUEST_TIMEOUT_SECONDS = 4.0


class LocationSuggestion(BaseModel):
    label: str
    name: str
    latitude: float
    longitude: float
    admin1: str | None = None
    country: str | None = None


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _matches_prefix(name: str, query: str) -> bool:
    # Open-Meteo uses a name followed by optional region/country qualifiers.
    prefix = query.split(",", 1)[0].strip()
    return bool(prefix) and _fold(name).startswith(_fold(prefix))


def _label(name: str, admin1: str | None, country: str | None) -> str:
    parts: list[str] = []
    for part in (name, admin1, country):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts)


def _from_open_meteo(data: dict[str, Any], query: str) -> list[LocationSuggestion]:
    suggestions: list[LocationSuggestion] = []
    for row in data.get("results") or []:
        name = row.get("name")
        latitude, longitude = row.get("latitude"), row.get("longitude")
        if not isinstance(name, str) or not _matches_prefix(name, query):
            continue
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            continue
        admin1, country = row.get("admin1"), row.get("country")
        suggestions.append(LocationSuggestion(
            label=_label(name, admin1, country), name=name,
            latitude=float(latitude), longitude=float(longitude),
            admin1=admin1, country=country,
        ))
    return suggestions


def _from_photon(data: dict[str, Any], query: str) -> list[LocationSuggestion]:
    suggestions: list[LocationSuggestion] = []
    for feature in data.get("features") or []:
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        name = properties.get("name") or properties.get("city") or properties.get("town") or properties.get("village")
        if not isinstance(name, str) or not _matches_prefix(name, query):
            continue
        if len(coordinates) < 2:
            continue
        longitude, latitude = coordinates[:2]
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            continue
        admin1 = properties.get("state") or properties.get("county")
        country = properties.get("country")
        suggestions.append(LocationSuggestion(
            label=_label(name, admin1, country), name=name,
            latitude=float(latitude), longitude=float(longitude),
            admin1=admin1, country=country,
        ))
    return suggestions


def _default_client_factory(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(**kwargs)


async def suggest_locations(
    query: str,
    *,
    client_factory: Callable[..., Any] = _default_client_factory,
) -> list[LocationSuggestion]:
    """Query Open-Meteo first, then use Komoot Photon on failure or no prefix hits."""
    cleaned = query.strip()
    if len(cleaned) < 2:
        return []

    try:
        async with client_factory(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(GEOCODING_URL, params={"name": cleaned, "count": 10, "language": "en"})
            response.raise_for_status()
            found = _from_open_meteo(response.json(), cleaned)
        if found:
            return found[:10]
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        pass

    try:
        async with client_factory(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(PHOTON_URL, params={"q": cleaned, "limit": 10, "lang": "en"})
            response.raise_for_status()
            return _from_photon(response.json(), cleaned)[:10]
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return []


@router.get("/suggest", response_model=list[LocationSuggestion])
async def location_suggestions(q: str = Query(min_length=2, max_length=120)):
    return await suggest_locations(q)
