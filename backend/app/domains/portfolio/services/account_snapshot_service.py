from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.services.account_calculator import (
    calculate_account_metrics,
)
from app.domains.portfolio.services.account_service import get_account
from app.domains.portfolio.services.ledger_service import get_cash_balance


@dataclass(frozen=True, slots=True)
class AccountFinancialSnapshot:
    account_id: int
    currency: str
    cash_balance: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    used_margin: Decimal
    free_margin: Decimal


async def get_account_financial_snapshot(
    session: AsyncSession,
    *,
    account_id: int,
    unrealized_pnl: Decimal,
    used_margin: Decimal,
) -> AccountFinancialSnapshot:
    """Build a read-only financial snapshot from ledger and market metrics."""

    # Validate external financial inputs before performing database queries.
    calculate_account_metrics(
        cash_balance=Decimal("0"),
        unrealized_pnl=unrealized_pnl,
        used_margin=used_margin,
    )

    account = await get_account(
        session,
        account_id=account_id,
    )

    cash_balance = await get_cash_balance(
        session,
        account_id=account_id,
    )

    metrics = calculate_account_metrics(
        cash_balance=cash_balance,
        unrealized_pnl=unrealized_pnl,
        used_margin=used_margin,
    )

    return AccountFinancialSnapshot(
        account_id=account.id,
        currency=account.currency,
        cash_balance=cash_balance,
        unrealized_pnl=unrealized_pnl,
        equity=metrics.equity,
        used_margin=metrics.used_margin,
        free_margin=metrics.free_margin,
    )
