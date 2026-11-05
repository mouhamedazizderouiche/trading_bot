
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.models import LedgerEntry, TradingAccount


MAX_ACCOUNT_ID = 2_147_483_647


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for different transaction data."""


class LedgerAccountNotFoundError(ValueError):
    """Raised when a requested trading account does not exist."""


class LedgerCurrencyMismatchError(ValueError):
    """Raised when a transaction currency differs from its account currency."""


def _validate_account_id(account_id: int) -> None:
    if (
        not isinstance(account_id, int)
        or isinstance(account_id, bool)
        or account_id <= 0
        or account_id > MAX_ACCOUNT_ID
    ):
        raise ValueError("account_id must be a valid positive integer")


def _validate_positive_amount(amount: Decimal) -> None:
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if amount <= Decimal("0"):
        raise ValueError("amount must be greater than zero")
    if amount.as_tuple().exponent < -8:
        raise ValueError("amount cannot have more than 8 decimal places")
    if amount.adjusted() >= 12:
        raise ValueError("amount exceeds the supported precision")


def _normalize_idempotency_key(key: str) -> str:
    if not isinstance(key, str):
        raise TypeError("idempotency_key must be a string")

    normalized = key.strip()

    if not normalized:
        raise ValueError("idempotency_key is required")
    if len(normalized) > 100:
        raise ValueError("idempotency_key cannot exceed 100 characters")

    return normalized


def _normalize_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    if not isinstance(reference, str):
        raise TypeError("reference must be a string or None")

    normalized = reference.strip()

    if len(normalized) > 100:
        raise ValueError("reference cannot exceed 100 characters")

    return normalized or None


def _normalize_currency(currency: str) -> str:
    if not isinstance(currency, str):
        raise ValueError("currency must be a 3-letter currency code")

    normalized = currency.strip().upper()

    if (
        len(normalized) != 3
        or not normalized.isascii()
        or not normalized.isalpha()
    ):
        raise ValueError("currency must be a 3-letter ASCII currency code")

    return normalized


def _check_existing_transaction(
    existing: LedgerEntry,
    *,
    account_id: int,
    entry_type: str,
    signed_amount: Decimal,
    currency: str,
    reference: str | None,
) -> LedgerEntry:
    same_request = (
        existing.account_id == account_id
        and existing.entry_type == entry_type
        and existing.amount == signed_amount
        and existing.currency == currency
        and existing.reference == reference
    )

    if not same_request:
        raise IdempotencyConflictError(
            "This idempotency_key has already been used "
            "for a different transaction"
        )

    return existing


async def _record_cash_movement(
    session: AsyncSession,
    *,
    account_id: int,
    entry_type: str,
    signed_amount: Decimal,
    currency: str,
    reference: str | None,
    idempotency_key: str,
) -> LedgerEntry:
    _validate_account_id(account_id)

    currency = _normalize_currency(currency)
    idempotency_key = _normalize_idempotency_key(idempotency_key)
    reference = _normalize_reference(reference)

    account = await session.get(TradingAccount, account_id)

    if account is None:
        raise LedgerAccountNotFoundError(
            f"Trading account {account_id} does not exist"
        )

    if account.currency.upper() != currency:
        raise LedgerCurrencyMismatchError(
            f"Transaction currency {currency} does not match "
            f"account currency {account.currency}"
        )

    statement = (
        insert(LedgerEntry)
        .values(
            account_id=account_id,
            entry_type=entry_type,
            amount=signed_amount,
            currency=currency,
            reference=reference,
            idempotency_key=idempotency_key,
            occurred_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=[LedgerEntry.idempotency_key]
        )
        .returning(LedgerEntry.id)
    )

    result = await session.execute(statement)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is not None:
        entry = await session.get(LedgerEntry, inserted_id)

        if entry is None:
            raise RuntimeError("Inserted ledger entry could not be retrieved")

        return entry

    existing = await session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.idempotency_key == idempotency_key
        )
    )

    if existing is None:
        raise RuntimeError(
            "Idempotency conflict occurred but the existing entry was not found"
        )

    return _check_existing_transaction(
        existing,
        account_id=account_id,
        entry_type=entry_type,
        signed_amount=signed_amount,
        currency=currency,
        reference=reference,
    )


async def record_deposit(
    session: AsyncSession,
    *,
    account_id: int,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerEntry:
    """Record a positive deposit."""
    _validate_positive_amount(amount)

    return await _record_cash_movement(
        session,
        account_id=account_id,
        entry_type="deposit",
        signed_amount=amount,
        currency=currency,
        reference=reference,
        idempotency_key=idempotency_key,
    )


async def record_withdrawal(
    session: AsyncSession,
    *,
    account_id: int,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerEntry:
    """Record a positive withdrawal input as a negative ledger amount."""
    _validate_positive_amount(amount)

    return await _record_cash_movement(
        session,
        account_id=account_id,
        entry_type="withdrawal",
        signed_amount=-amount,
        currency=currency,
        reference=reference,
        idempotency_key=idempotency_key,
    )


class ReversalConflictError(ValueError):
    """Raised when an entry already has a different reversal."""


async def record_reversal(
    session: AsyncSession,
    *,
    original_entry_id: int,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerEntry:
    """Record an immutable compensating entry for an original ledger entry."""

    if (
        not isinstance(original_entry_id, int)
        or isinstance(original_entry_id, bool)
        or original_entry_id <= 0
    ):
        raise ValueError("original_entry_id must be a positive integer")

    idempotency_key = _normalize_idempotency_key(idempotency_key)
    reference = _normalize_reference(reference)

    original = await session.scalar(
        select(LedgerEntry)
        .where(LedgerEntry.id == original_entry_id)
        .with_for_update()
    )

    if original is None:
        raise ValueError(
            f"Ledger entry {original_entry_id} does not exist"
        )

    if original.entry_type == "reversal":
        raise ValueError("A reversal cannot reverse another reversal")

    existing_reversal = await session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reversal_of_id == original.id
        )
    )

    if existing_reversal is not None:
        if existing_reversal.idempotency_key != idempotency_key:
            raise ReversalConflictError(
                "This ledger entry has already been reversed"
            )

        if existing_reversal.reference != reference:
            raise IdempotencyConflictError(
                "This idempotency_key has already been used "
                "for a different reversal request"
            )

        return existing_reversal

    statement = (
        insert(LedgerEntry)
        .values(
            account_id=original.account_id,
            entry_type="reversal",
            amount=-original.amount,
            currency=original.currency,
            reference=reference,
            idempotency_key=idempotency_key,
            reversal_of_id=original.id,
            occurred_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing()
        .returning(LedgerEntry.id)
    )

    result = await session.execute(statement)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is not None:
        entry = await session.get(LedgerEntry, inserted_id)

        if entry is None:
            raise RuntimeError(
                "Inserted reversal could not be retrieved"
            )

        return entry

    existing_by_key = await session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.idempotency_key == idempotency_key
        )
    )

    if existing_by_key is not None:
        if (
            existing_by_key.entry_type == "reversal"
            and existing_by_key.reversal_of_id == original.id
            and existing_by_key.reference == reference
        ):
            return existing_by_key

        raise IdempotencyConflictError(
            "This idempotency_key has already been used "
            "for a different transaction"
        )

    existing_reversal = await session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reversal_of_id == original.id
        )
    )

    if existing_reversal is not None:
        raise ReversalConflictError(
            "This ledger entry has already been reversed"
        )

    raise RuntimeError(
        "Reversal insert was rejected but no conflicting entry was found"
    )


async def get_cash_balance(
    session: AsyncSession,
    *,
    account_id: int,
) -> Decimal:
    """Calculate cash balance from signed ledger entries."""
    _validate_account_id(account_id)

    result = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.account_id == account_id
        )
    )

    return result if isinstance(result, Decimal) else Decimal(str(result or 0))
