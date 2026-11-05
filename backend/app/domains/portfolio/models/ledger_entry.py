from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    __table_args__ = (
        CheckConstraint(
            "entry_type IN "
            "('deposit', 'withdrawal', 'realized_pnl', "
            "'commission', 'swap', 'reversal')",
            name="ck_ledger_entry_type",
        ),
        CheckConstraint(
            "amount != 0",
            name="ck_ledger_amount_nonzero",
        ),
        CheckConstraint(
            "(entry_type != 'deposit' OR amount > 0) AND "
            "(entry_type != 'withdrawal' OR amount < 0) AND "
            "(entry_type != 'commission' OR amount < 0)",
            name="ck_ledger_amount_direction",
        ),
        CheckConstraint(
            "(entry_type = 'reversal' AND reversal_of_id IS NOT NULL) OR "
            "(entry_type != 'reversal' AND reversal_of_id IS NULL)",
            name="ck_ledger_reversal_reference",
        ),
        UniqueConstraint(
            "reversal_of_id",
            name="uq_ledger_entries_reversal_of_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"),
        nullable=False,
        index=True,
    )

    entry_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    reversal_of_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "ledger_entries.id",
            name="fk_ledger_entries_reversal_of_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
