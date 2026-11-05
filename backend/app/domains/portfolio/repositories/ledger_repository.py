from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.models import LedgerEntry


async def list_account_transactions(
    session: AsyncSession,
    *,
    account_id: int,
    offset: int,
    limit: int,
) -> tuple[list[LedgerEntry], int]:
    count_statement = (
        select(func.count())
        .select_from(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
    )

    total = await session.scalar(count_statement)

    statement = (
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
        .order_by(
            LedgerEntry.occurred_at.desc(),
            LedgerEntry.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await session.scalars(statement)

    return list(result.all()), int(total or 0)