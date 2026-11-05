from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    entry_type: str
    amount: Decimal
    currency: str
    reference: str | None
    reversal_of_id: int | None
    occurred_at: datetime
    created_at: datetime


class LedgerTransactionPage(BaseModel):
    items: list[LedgerEntryRead]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
