from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.chart.models import ChartRequest


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("enter a valid email address")
        return normalized


class UserResponse(BaseModel):
    id: int
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    user: UserResponse
    question_balance: int


class WalletResponse(BaseModel):
    balance: int


class MeResponse(BaseModel):
    user: UserResponse
    question_balance: int


class WalletAddRequest(BaseModel):
    amount: int = Field(default=10, ge=1, le=10)


class QuestionRatingRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("rating must be -1 or 1")
        return value


class QuestionRatingResponse(BaseModel):
    question_id: int
    rating: int


class ProfileRequest(ChartRequest):
    label: str = Field(default="My birth chart", min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    birth_time_unknown: bool = False
    chart_style: Literal["north", "south"] = "north"


class ProfileResponse(BaseModel):
    id: int
    label: str
    display_name: str | None
    birth_date: date
    birth_time: time
    birth_time_unknown: bool
    timezone: str
    location: str
    latitude: float | None
    longitude: float | None
    chart_facts: list[str]
    chart_style: Literal["north", "south"] = "north"

    model_config = ConfigDict(from_attributes=True)


class LedgerEntryResponse(BaseModel):
    id: int
    question_id: int | None
    amount: int
    balance_after: int
    reason: str
    note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuestionCreate(BaseModel):
    question_text: str = Field(min_length=1, max_length=12000)
    answer_text: str | None = Field(default=None, max_length=50000)
    birth_profile_id: int | None = None
    facts_used: list[str] = Field(default_factory=list)
    llm_provider: str | None = Field(default=None, max_length=80)
    llm_model: str | None = Field(default=None, max_length=160)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: Decimal | None = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=8)


class QuestionAskRequest(BaseModel):
    question_text: str = Field(min_length=1, max_length=12000)
    chart: ChartRequest
    profile_label: str = Field(default="My birth chart", min_length=1, max_length=120)


class AskQuestionRequest(BaseModel):
    question_text: str | None = Field(default=None, min_length=1, max_length=12000)
    draft_id: int | None = Field(default=None, ge=1)
    retry_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def question_or_draft(self):
        if not self.question_text and self.draft_id is None and self.retry_id is None:
            raise ValueError("provide question_text, a saved draft_id, or a retry_id")
        if sum(bool(value) for value in (self.question_text, self.draft_id, self.retry_id)) > 1:
            raise ValueError("provide only one of question_text, draft_id, or retry_id")
        return self


class QuestionResponse(QuestionCreate):
    id: int
    user_id: int
    created_at: datetime
    wallet_balance: int
    api_key_slot: str | None = None
    status: str = "answered"

    model_config = ConfigDict(from_attributes=True)


class QuestionHistoryItem(BaseModel):
    id: int
    question_text: str
    answer_text: str | None
    status: str
    rating: int | None
    facts_used: list[str]
    highlighted_houses: list[int] = Field(default_factory=list)
    llm_provider: str | None
    llm_model: str | None
    api_key_slot: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
