import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    clear_session_cookie,
    ensure_auth_configured,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.chart.calculator import calculate_chart
from app.chart.models import ChartRequest
from app.llm import generate_answer
from app.llm.routing import route_question, target_houses_for_question
from .models import AppEvent, BirthProfile, Question, User, Wallet, WalletLedger
from .schemas import (
    AuthResponse,
    AskQuestionRequest,
    LedgerEntryResponse,
    QuestionCreate,
    QuestionAskRequest,
    QuestionHistoryItem,
    QuestionRatingRequest,
    QuestionRatingResponse,
    QuestionResponse,
    MeResponse,
    ProfileRequest,
    ProfileResponse,
    RegisterRequest,
    UserResponse,
    WalletAddRequest,
    WalletResponse,
)
from .session import get_db, get_session_factory
from .wallet import adjust_wallet

router = APIRouter(tags=["account"])
LOGGER = logging.getLogger("melooha.api.ask")
ASK_FAILURE_MESSAGE = "I couldn't complete that reading right now. Your question credit has been returned. Please try again shortly."


def _record_first_question(session: Session, user_id: int) -> None:
    exists = session.scalar(select(AppEvent.id).where(
        AppEvent.user_id == user_id, AppEvent.event == "first_question",
    ).limit(1))
    if exists is None:
        session.add(AppEvent(user_id=user_id, event="first_question"))


def _profile_cache_key(body: ProfileRequest) -> str:
    chart_input = body.model_dump(exclude={"label", "display_name", "chart_style"}, mode="json")
    return hashlib.sha256(json.dumps(chart_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest, response: Response, session: Session = Depends(get_db)):
    ensure_auth_configured()
    user = User(email=body.email, password_hash=hash_password(body.password))
    try:
        with session.begin():
            session.add(user)
            session.flush()
            session.add(AppEvent(user_id=user.id, event="signup"))
            wallet = Wallet(user_id=user.id, balance=1)
            session.add(wallet)
            session.add(WalletLedger(user_id=user.id, amount=1, balance_after=1, reason="signup", note="Free first question"))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    set_session_cookie(response, user.id)
    return AuthResponse(user=UserResponse.model_validate(user), question_balance=1)


@router.post("/auth/login", response_model=AuthResponse)
def login(body: RegisterRequest, response: Response, session: Session = Depends(get_db)):
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    wallet = session.get(Wallet, user.id)
    set_session_cookie(response, user.id)
    return AuthResponse(user=UserResponse.model_validate(user), question_balance=wallet.balance if wallet else 0)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=AuthResponse)
@router.get("/me", response_model=MeResponse)
def who_am_i(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    wallet = session.get(Wallet, user.id)
    return AuthResponse(user=UserResponse.model_validate(user), question_balance=wallet.balance if wallet else 0)


@router.get("/wallet", response_model=WalletResponse)
def get_wallet(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    wallet = session.get(Wallet, user.id)
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    return WalletResponse(balance=wallet.balance)


@router.post("/wallet/add", response_model=WalletResponse)
def add_questions(
    body: WalletAddRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if os.getenv("APP_ENV", "").lower() not in {"dev", "development", "test"}:
        raise HTTPException(status_code=403, detail="Question top-ups are not enabled yet.")
    with session.begin():
        balance = adjust_wallet(
            session,
            user_id=user.id,
            amount=body.amount,
            reason="dummy_credit",
            note="Development question credit; no payment",
        )
    if balance is None:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    return WalletResponse(balance=balance)


@router.post("/profile", response_model=ProfileResponse)
def save_profile(
    body: ProfileRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    cache_key = _profile_cache_key(body)
    with session.begin():
        profile = session.scalar(select(BirthProfile).where(
            BirthProfile.user_id == user.id,
            BirthProfile.cache_key == cache_key,
        ))
        if profile is None:
            profile = BirthProfile(
                user_id=user.id,
                label=body.label,
                display_name=body.display_name,
                birth_date=body.birth_date,
                birth_time=body.birth_time,
                birth_time_unknown=body.birth_time_unknown,
                chart_style=body.chart_style,
                timezone=body.timezone,
                location=body.location,
                latitude=body.latitude,
                longitude=body.longitude,
                cache_key=cache_key,
                chart_facts=[],
                chart_data={},
                calculated_at=datetime.now(timezone.utc),
            )
            session.add(profile)
        else:
            profile.label = body.label
            profile.display_name = body.display_name
            profile.birth_time_unknown = body.birth_time_unknown
            profile.chart_style = body.chart_style
            profile.updated_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(profile)
    return ProfileResponse.model_validate(profile)


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    profile = session.scalar(
        select(BirthProfile).where(BirthProfile.user_id == user.id)
        .order_by(BirthProfile.updated_at.desc(), BirthProfile.id.desc())
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Add your birth details to create a chart profile.")
    return ProfileResponse.model_validate(profile)


@router.post("/wallet/spend", response_model=WalletResponse)
def spend_question(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    with session.begin():
        balance = adjust_wallet(session, user_id=user.id, amount=-1, reason="question", note="Question credit used")
        if balance is None:
            raise HTTPException(status_code=409, detail="No questions remain in this wallet.")
    return WalletResponse(balance=balance)


@router.get("/wallet/ledger", response_model=list[LedgerEntryResponse])
def wallet_ledger(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    entries = session.scalars(
        select(WalletLedger).where(WalletLedger.user_id == user.id).order_by(WalletLedger.id.desc())
    ).all()
    return [LedgerEntryResponse.model_validate(entry) for entry in entries]


@router.post("/questions", response_model=QuestionResponse, status_code=201)
def save_question(body: QuestionCreate, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    question = Question(user_id=user.id, **body.model_dump())
    with session.begin():
        if body.birth_profile_id is not None:
            owned_profile = session.scalar(select(BirthProfile.id).where(
                BirthProfile.id == body.birth_profile_id,
                BirthProfile.user_id == user.id,
            ))
            if owned_profile is None:
                raise HTTPException(status_code=404, detail="Birth profile not found.")
        session.add(question)
        session.flush()
        _record_first_question(session, user.id)
        balance = adjust_wallet(
            session,
            user_id=user.id,
            amount=-1,
            reason="question",
            note="Question answered",
            question_id=question.id,
        )
        if balance is None:
            raise HTTPException(status_code=409, detail="No questions remain in this wallet.")
    return QuestionResponse(**body.model_dump(), id=question.id, user_id=user.id, created_at=question.created_at, wallet_balance=balance)


@router.post("/questions/ask", response_model=QuestionResponse, status_code=201)
def ask_astrologer(
    body: QuestionAskRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    chart = calculate_chart(body.chart)
    facts_used = route_question(body.question_text, chart.facts)
    generated = generate_answer(body.question_text, facts_used)
    if not generated.succeeded:
        raise HTTPException(status_code=503, detail=generated.answer)

    cache_json = body.chart.model_dump(mode="json")
    cache_key = hashlib.sha256(json.dumps(cache_json, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with session.begin():
        profile = session.scalar(select(BirthProfile).where(
            BirthProfile.user_id == user.id,
            BirthProfile.cache_key == cache_key,
        ))
        if profile is None:
            profile = BirthProfile(
                user_id=user.id,
                label=body.profile_label,
                birth_date=body.chart.birth_date,
                birth_time=body.chart.birth_time,
                timezone=body.chart.timezone,
                location=body.chart.location,
                latitude=body.chart.latitude,
                longitude=body.chart.longitude,
                cache_key=cache_key,
                chart_facts=chart.facts,
                chart_data=chart.model_dump(mode="json"),
                calculated_at=datetime.now(timezone.utc),
            )
            session.add(profile)
            session.flush()
        else:
            profile.label = body.profile_label
            profile.chart_facts = chart.facts
            profile.chart_data = chart.model_dump(mode="json")
            profile.calculated_at = datetime.now(timezone.utc)

        _record_first_question(session, user.id)

        question = Question(
            user_id=user.id,
            birth_profile_id=profile.id,
            question_text=body.question_text,
            answer_text=generated.answer,
            facts_used=facts_used,
            llm_provider=generated.provider,
            llm_model=generated.model,
            api_key_slot=generated.api_key_slot,
            prompt_tokens=generated.prompt_tokens,
            completion_tokens=generated.completion_tokens,
            total_tokens=generated.total_tokens,
            cost_usd=generated.estimated_cost_usd,
        )
        session.add(question)
        session.flush()
        balance = adjust_wallet(
            session,
            user_id=user.id,
            amount=-1,
            reason="question",
            note="Astrologer answer generated",
            question_id=question.id,
        )
        if balance is None:
            raise HTTPException(status_code=409, detail="No questions remain in this wallet.")

    return QuestionResponse(
        id=question.id,
        user_id=user.id,
        question_text=question.question_text,
        answer_text=question.answer_text,
        birth_profile_id=question.birth_profile_id,
        facts_used=question.facts_used,
        llm_provider=question.llm_provider,
        llm_model=question.llm_model,
        api_key_slot=question.api_key_slot,
        prompt_tokens=question.prompt_tokens,
        completion_tokens=question.completion_tokens,
        total_tokens=question.total_tokens,
        cost_usd=question.cost_usd if question.cost_usd is not None else Decimal("0"),
        created_at=question.created_at,
        wallet_balance=balance,
    )


@router.post("/ask")
def ask_with_sse(
    body: AskQuestionRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Reserve one credit, then stream only a checked answer as SSE."""
    retry_without_charge = False
    with session.begin():
        if body.retry_id is not None:
            question = session.scalar(select(Question).where(
                Question.id == body.retry_id,
                Question.user_id == user.id,
                Question.status.in_({"failed", "pending"}),
            ).with_for_update())
            if question is None:
                raise HTTPException(status_code=404, detail="That failed answer is no longer available to retry.")
            question.status = "pending"
            question.answer_text = None
            question.facts_used = []
            question_id = question.id
            question_text = question.question_text
            wallet = session.get(Wallet, user.id)
            balance = wallet.balance if wallet is not None else 0
            profile_id = question.birth_profile_id
            if profile_id is None:
                profile = session.scalar(
                    select(BirthProfile).where(BirthProfile.user_id == user.id)
                    .order_by(BirthProfile.updated_at.desc(), BirthProfile.id.desc())
                )
                profile_id = profile.id if profile else None
            if profile_id is None:
                raise HTTPException(status_code=409, detail="Add your birth details before retrying this answer.")
            out_of_balance = False
            retry_without_charge = True
        elif body.draft_id is not None:
            question = session.scalar(select(Question).where(
                Question.id == body.draft_id,
                Question.user_id == user.id,
                Question.status == "draft",
            ).with_for_update())
            if question is None:
                raise HTTPException(status_code=404, detail="Saved question draft not found.")
            if body.question_text:
                question.question_text = body.question_text
            question.answer_text = None
            question.status = "pending"
        else:
            question = Question(
                user_id=user.id,
                question_text=body.question_text or "",
                answer_text=None,
                status="pending",
                facts_used=[],
            )
            session.add(question)
            session.flush()
            _record_first_question(session, user.id)
        if body.retry_id is None:
            question_id = question.id
            question_text = question.question_text
            balance = adjust_wallet(
                session,
                user_id=user.id,
                amount=-1,
                reason="question",
                note="Astrologer question submitted",
                question_id=question_id,
            )
            if balance is None:
                question.status = "draft"
                wallet = session.get(Wallet, user.id)
                balance = wallet.balance if wallet is not None else 0
                out_of_balance = True
                profile_id = None
            else:
                out_of_balance = False
                profile = session.scalar(
                    select(BirthProfile).where(BirthProfile.user_id == user.id)
                    .order_by(BirthProfile.updated_at.desc(), BirthProfile.id.desc())
                )
                if profile is None:
                    raise HTTPException(status_code=409, detail="Add your birth details before asking a question.")
                profile_id = profile.id
                question.birth_profile_id = profile_id

        question.highlighted_houses = target_houses_for_question(question_text)

    if out_of_balance:
        return JSONResponse(
            status_code=402,
            content={
                "status": "out_of_balance",
                "question_id": question_id,
                "question_text": question_text,
                "wallet_balance": balance,
            },
        )

    def stream_events():
        answer_record: Question | None = None
        chart_facts: list[str] = []
        all_chart_facts: list[str] = []
        generated = None
        failure_message = ASK_FAILURE_MESSAGE
        yield _sse("started", {"question_id": question_id, "wallet_balance": balance})
        try:
            factory = get_session_factory()
            with factory() as db:
                profile = db.scalar(select(BirthProfile).where(
                    BirthProfile.id == profile_id,
                    BirthProfile.user_id == user.id,
                ))
                if profile is None:
                    raise ValueError("Birth profile is unavailable")
                request = ChartRequest(
                    birth_date=profile.birth_date,
                    birth_time=profile.birth_time,
                    timezone=profile.timezone,
                    location=profile.location,
                    latitude=profile.latitude,
                    longitude=profile.longitude,
                )

            chart = calculate_chart(request)
            all_chart_facts = list(chart.facts)
            if profile.birth_time_unknown:
                all_chart_facts.append(
                    f"F{len(all_chart_facts) + 1:03d} : Birth time was marked unknown; time-dependent placements are approximate"
                )
            chart_facts = route_question(question_text, all_chart_facts)
            # User identity and profile metadata are intentionally not passed to any LLM.
            generated = generate_answer(question_text, chart_facts, stream=True)
            if not generated.succeeded:
                raise RuntimeError("All configured answer providers failed")
        except Exception as exc:
            LOGGER.warning("Question generation failed question_id=%s error=%s", question_id, type(exc).__name__)
            generated = None

        with get_session_factory()() as db:
            with db.begin():
                answer_record = db.scalar(select(Question).where(
                    Question.id == question_id,
                    Question.user_id == user.id,
                ))
                if answer_record is None:
                    return
                answer_record.facts_used = chart_facts
                if generated is None:
                    answer_record.status = "failed"
                    answer_record.answer_text = failure_message
                    if retry_without_charge:
                        wallet = db.get(Wallet, user.id)
                        balance_after = wallet.balance if wallet is not None else 0
                    else:
                        refund_balance = adjust_wallet(
                            db,
                            user_id=user.id,
                            amount=1,
                            reason="refund",
                            note=f"Refund for failed answer to question #{question_id}",
                        )
                        balance_after = refund_balance if refund_balance is not None else 0
                else:
                    answer_record.status = "answered"
                    answer_record.answer_text = generated.answer
                    answer_record.llm_provider = generated.provider
                    answer_record.llm_model = generated.model
                    answer_record.api_key_slot = generated.api_key_slot
                    answer_record.prompt_tokens = generated.prompt_tokens
                    answer_record.completion_tokens = generated.completion_tokens
                    answer_record.total_tokens = generated.total_tokens
                    answer_record.cost_usd = generated.estimated_cost_usd
                    answer_record.birth_profile_id = profile_id
                    answer_record_profile = db.get(BirthProfile, profile_id)
                    if answer_record_profile is not None:
                        answer_record_profile.chart_facts = all_chart_facts
                        answer_record_profile.chart_data = chart.model_dump(mode="json")
                        answer_record_profile.calculated_at = datetime.now(timezone.utc)
                    balance_after = balance

        yield _sse("meta", {
            "question_id": question_id,
            "facts_used": chart_facts,
            "wallet_balance": balance_after,
            "highlighted_houses": target_houses_for_question(question_text),
        })
        if generated is None:
            yield _sse("failed", {
                "question_id": question_id,
                "message": failure_message,
                "wallet_balance": balance_after,
            })
            return
        answer_text = generated.answer
        for start in range(0, len(answer_text), 72):
            yield _sse("chunk", {"text": answer_text[start:start + 72]})
        yield _sse("complete", {
            "question_id": question_id,
            "answer_text": answer_text,
            "facts_used": chart_facts,
            "wallet_balance": balance_after,
            "status": "answered",
            "highlighted_houses": target_houses_for_question(question_text),
        })

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/questions", response_model=list[QuestionHistoryItem])
@router.get("/history", response_model=list[QuestionHistoryItem])
def question_history(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1–100 and offset must be non-negative.")
    questions = session.scalars(
        select(Question).where(Question.user_id == user.id).order_by(Question.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [QuestionHistoryItem.model_validate(question) for question in questions]


@router.post("/questions/{question_id}/rating", response_model=QuestionRatingResponse)
def rate_question(
    question_id: int,
    body: QuestionRatingRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    with session.begin():
        question = session.scalar(select(Question).where(
            Question.id == question_id,
            Question.user_id == user.id,
        ))
        if question is None:
            raise HTTPException(status_code=404, detail="Answer not found.")
        if question.status != "answered":
            raise HTTPException(status_code=409, detail="Only answered questions can be rated.")
        question.rating = body.rating
    return QuestionRatingResponse(question_id=question_id, rating=body.rating)
