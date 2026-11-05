from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.portfolio.repositories.ledger_repository import (
    list_account_transactions,
)
from app.domains.portfolio.schemas import (
    AccountCreate,
    AccountRead,
    CashBalanceRead,
    CashMovementCreate,
    LedgerEntryRead,
    LedgerTransactionPage,
)
from app.domains.portfolio.services.account_service import (
    AccountNotFoundError,
    AccountValidationError,
    create_account,
    get_account,
    list_accounts,
)
from app.domains.portfolio.services.ledger_service import (
    IdempotencyConflictError,
    LedgerAccountNotFoundError,
    LedgerCurrencyMismatchError,
    get_cash_balance,
    record_deposit,
    record_withdrawal,
)
from app.infrastructure.database.session import get_db


router = APIRouter(
    prefix="/api/v1/accounts",
    tags=["Accounts"],
)


def _raise_ledger_http_error(exc: Exception) -> None:
    if isinstance(exc, IdempotencyConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if isinstance(exc, (AccountNotFoundError, LedgerAccountNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if isinstance(exc, (AccountValidationError, LedgerCurrencyMismatchError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if isinstance(exc, (ValueError, TypeError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    raise exc


@router.post(
    "",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_account_endpoint(
    payload: AccountCreate,
    session: AsyncSession = Depends(get_db),
):
    try:
        async with session.begin():
            account = await create_account(
                session,
                name=payload.name,
                currency=payload.currency,
            )

        return account

    except AccountValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[AccountRead])
async def list_accounts_endpoint(
    session: AsyncSession = Depends(get_db),
):
    return await list_accounts(session)


@router.get("/{account_id}", response_model=AccountRead)
async def get_account_endpoint(
    account_id: int = Path(gt=0, le=2147483647),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await get_account(session, account_id=account_id)

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except AccountValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{account_id}/deposits",
    response_model=LedgerEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_deposit_endpoint(
    payload: CashMovementCreate,
    account_id: int = Path(gt=0, le=2147483647),
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=100,
    ),
    session: AsyncSession = Depends(get_db),
):
    try:
        async with session.begin():
            account = await get_account(session, account_id=account_id)

            entry = await record_deposit(
                session,
                account_id=account.id,
                amount=payload.amount,
                currency=account.currency,
                idempotency_key=idempotency_key,
                reference=payload.reference,
            )

        return entry

    except (
        IdempotencyConflictError,
        LedgerAccountNotFoundError,
        LedgerCurrencyMismatchError,
        AccountNotFoundError,
        AccountValidationError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_ledger_http_error(exc)


@router.post(
    "/{account_id}/withdrawals",
    response_model=LedgerEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_withdrawal_endpoint(
    payload: CashMovementCreate,
    account_id: int = Path(gt=0, le=2147483647),
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=100,
    ),
    session: AsyncSession = Depends(get_db),
):
    try:
        async with session.begin():
            account = await get_account(session, account_id=account_id)

            entry = await record_withdrawal(
                session,
                account_id=account.id,
                amount=payload.amount,
                currency=account.currency,
                idempotency_key=idempotency_key,
                reference=payload.reference,
            )

        return entry

    except (
        IdempotencyConflictError,
        LedgerAccountNotFoundError,
        LedgerCurrencyMismatchError,
        AccountNotFoundError,
        AccountValidationError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_ledger_http_error(exc)


@router.get(
    "/{account_id}/balance",
    response_model=CashBalanceRead,
)
async def get_account_balance_endpoint(
    account_id: int = Path(gt=0, le=2147483647),
    session: AsyncSession = Depends(get_db),
):
    try:
        account = await get_account(session, account_id=account_id)

        balance = await get_cash_balance(
            session,
            account_id=account.id,
        )

        return CashBalanceRead(
            account_id=account.id,
            currency=account.currency,
            cash_balance=balance,
        )

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{account_id}/transactions",
    response_model=LedgerTransactionPage,
)
async def get_account_transactions_endpoint(
    account_id: int = Path(gt=0, le=2147483647),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    try:
        await get_account(session, account_id=account_id)

        entries, total = await list_account_transactions(
            session,
            account_id=account_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

        return LedgerTransactionPage(
            items=entries,
            total=total,
            page=page,
            page_size=page_size,
        )

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
