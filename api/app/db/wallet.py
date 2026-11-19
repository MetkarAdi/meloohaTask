from sqlalchemy import update
from sqlalchemy.orm import Session

from .models import Wallet, WalletLedger


def adjust_wallet(
    session: Session,
    *,
    user_id: int,
    amount: int,
    reason: str,
    note: str | None = None,
    question_id: int | None = None,
) -> int | None:
    """Atomically change a wallet and append its ledger row in the caller's transaction."""
    if amount == 0:
        raise ValueError("wallet changes cannot be zero")
    statement = update(Wallet).where(Wallet.user_id == user_id)
    if amount < 0:
        statement = statement.where(Wallet.balance >= -amount)
    statement = statement.values(balance=Wallet.balance + amount).returning(Wallet.balance)
    balance_after = session.execute(statement).scalar_one_or_none()
    if balance_after is None:
        return None
    session.add(WalletLedger(
        user_id=user_id,
        question_id=question_id,
        amount=amount,
        balance_after=balance_after,
        reason=reason,
        note=note,
    ))
    return balance_after
