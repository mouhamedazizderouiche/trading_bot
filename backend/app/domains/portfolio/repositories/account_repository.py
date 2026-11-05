from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.models import TradingAccount


async def create_account(
    session: AsyncSession,
    *,
    name: str,
    currency: str,
) -> TradingAccount:
    account = TradingAccount(
        name=name,
        currency=currency,
    )

    session.add(account)
    await session.flush()

    return account


async def get_account(
    session: AsyncSession,
    *,
    account_id: int,
) -> TradingAccount | None:
    return await session.get(TradingAccount, account_id)


async def list_accounts(
    session: AsyncSession,
) -> list[TradingAccount]:
    result = await session.scalars(
        select(TradingAccount).order_by(TradingAccount.id)
    )

    return list(result.all())
