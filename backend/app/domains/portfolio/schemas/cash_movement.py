from decimal import Decimal

from pydantic import BaseModel, Field


class CashMovementCreate(BaseModel):
    amount: Decimal = Field(
        gt=0,
        max_digits=20,
        decimal_places=8,
    )
    reference: str | None = Field(
        default=None,
        max_length=100,
    )


class CashBalanceRead(BaseModel):
    account_id: int
    currency: str
    cash_balance: Decimal