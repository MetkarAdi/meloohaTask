from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class ChartRequest(BaseModel):
    birth_date: date
    birth_time: time
    timezone: str = "Asia/Kolkata"
    location: str = Field(min_length=2, description="Birthplace name, such as Dhule, Maharashtra, India")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an IANA timezone, for example Asia/Kolkata") from exc
        return value

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class PlanetPosition(BaseModel):
    name: str
    sign: str
    house: int = Field(ge=1, le=12)
    retrograde: bool
    nakshatra: str


class DashaPeriod(BaseModel):
    lord: str
    start_date: date
    end_date: date


class TransitPosition(BaseModel):
    planet: Literal["Jupiter", "Saturn"]
    sign: str
    house: int = Field(ge=1, le=12)
    retrograde: bool
    nakshatra: str


class ChartResponse(BaseModel):
    birth_date: date
    birth_time: time
    timezone: str
    location: str
    ayanamsa: Literal["Lahiri"] = "Lahiri"
    house_system: Literal["Whole Sign"] = "Whole Sign"
    lagna_sign: str
    planets: list[PlanetPosition] = Field(min_length=9, max_length=9)
    current_mahadasha: DashaPeriod
    current_antardasha: DashaPeriod
    current_pratyantardasha: DashaPeriod
    transits: list[TransitPosition] = Field(min_length=2, max_length=2)
    facts: list[str]
