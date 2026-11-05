from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.models import TradingAccount
from app.domains.portfolio.repositories import account_repository


MAX_ACCOUNT_ID = 2_147_483_647


class AccountValidationError(ValueError):
    """Raised when account input violates business rules."""


class AccountNotFoundError(LookupError):
    """Raised when a trading account does not exist."""


def _normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise AccountValidationError("Account name must be a string")

    normalized = name.strip()

    if not normalized:
        raise AccountValidationError("Account name cannot be empty")

    if len(normalized) > 100:
        raise AccountValidationError(
            "Account name cannot exceed 100 characters"
        )

    return normalized


def _normalize_currency(currency: str) -> str:
    if not isinstance(currency, str):
        raise AccountValidationError("Currency must be a string")

    normalized = currency.strip().upper()

    if (
        len(normalized) != 3
        or not normalized.isascii()
        or not normalized.isalpha()
    ):
        raise AccountValidationError(
            "Currency must be a 3-letter ASCII currency code"
        )

    return normalized


def _validate_account_id(account_id: int) -> None:
    if (
        not isinstance(account_id, int)
        or isinstance(account_id, bool)
        or account_id <= 0
        or account_id > MAX_ACCOUNT_ID
    ):
        raise AccountValidationError(
            f"Account ID must be between 1 and {MAX_ACCOUNT_ID}"
        )


async def create_account(
    session: AsyncSession,
    *,
    name: str,
    currency: str = "USD",
) -> TradingAccount:
    """Create an account without creating or modifying its balance."""

    normalized_name = _normalize_name(name)
    normalized_currency = _normalize_currency(currency)

    return await account_repository.create_account(
        session,
        name=normalized_name,
        currency=normalized_currency,
    )


async def get_account(
    session: AsyncSession,
    *,
    account_id: int,
) -> TradingAccount:
    _validate_account_id(account_id)

    account = await account_repository.get_account(
        session,
        account_id=account_id,
    )

    if account is None:
        raise AccountNotFoundError(
            f"Trading account {account_id} does not exist"
        )

    return account


async def list_accounts(
    session: AsyncSession,
) -> list[TradingAccount]:
    return await account_repository.list_accounts(session)
