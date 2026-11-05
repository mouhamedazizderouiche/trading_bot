"""add immutable ledger reversals

Revision ID: 2af76ff22cec
Revises: daaf02960690
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2af76ff22cec"
down_revision: Union[str, Sequence[str], None] = "daaf02960690"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the reversal reference.
    op.add_column(
        "ledger_entries",
        sa.Column("reversal_of_id", sa.Integer(), nullable=True),
    )

    op.create_unique_constraint(
        "uq_ledger_entries_reversal_of_id",
        "ledger_entries",
        ["reversal_of_id"],
    )

    op.create_foreign_key(
        "fk_ledger_entries_reversal_of_id",
        "ledger_entries",
        "ledger_entries",
        ["reversal_of_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Allow reversal as a ledger entry type.
    op.drop_constraint(
        "ck_ledger_entry_type",
        "ledger_entries",
        type_="check",
    )

    op.create_check_constraint(
        "ck_ledger_entry_type",
        "ledger_entries",
        "entry_type IN "
        "('deposit', 'withdrawal', 'realized_pnl', "
        "'commission', 'swap', 'reversal')",
    )

    # A reversal must reference an original entry.
    op.create_check_constraint(
        "ck_ledger_reversal_reference",
        "ledger_entries",
        "(entry_type = 'reversal' AND reversal_of_id IS NOT NULL) "
        "OR (entry_type != 'reversal' AND reversal_of_id IS NULL)",
    )

    # Validate every reversal against its original entry.
    op.execute("""
        CREATE FUNCTION validate_ledger_reversal()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            original_account_id INTEGER;
            original_amount NUMERIC(20, 8);
            original_currency VARCHAR(3);
            original_entry_type VARCHAR(30);
        BEGIN
            IF NEW.entry_type <> 'reversal' THEN
                RETURN NEW;
            END IF;

            SELECT account_id, amount, currency, entry_type
            INTO original_account_id, original_amount,
                 original_currency, original_entry_type
            FROM ledger_entries
            WHERE id = NEW.reversal_of_id
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Original ledger entry does not exist';
            END IF;

            IF original_entry_type = 'reversal' THEN
                RAISE EXCEPTION 'A reversal cannot reverse another reversal';
            END IF;

            IF NEW.account_id <> original_account_id THEN
                RAISE EXCEPTION 'Reversal account must match original account';
            END IF;

            IF NEW.currency <> original_currency THEN
                RAISE EXCEPTION 'Reversal currency must match original currency';
            END IF;

            IF NEW.amount <> -original_amount THEN
                RAISE EXCEPTION 'Reversal amount must be the exact opposite of the original';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)

    op.execute("""
        CREATE TRIGGER trg_validate_ledger_reversal
        BEFORE INSERT ON ledger_entries
        FOR EACH ROW
        EXECUTE FUNCTION validate_ledger_reversal();
    """)

    # Make the ledger append-only.
    op.execute("""
        CREATE FUNCTION prevent_ledger_mutation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Ledger entries are immutable; use a compensating reversal'
                USING ERRCODE = '55000';
        END;
        $$;
    """)

    op.execute("""
        CREATE TRIGGER trg_prevent_ledger_mutation
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW
        EXECUTE FUNCTION prevent_ledger_mutation();
    """)


def downgrade() -> None:
    # Remove triggers before removing their functions.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_prevent_ledger_mutation ON ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_ledger_reversal ON ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_ledger_reversal()")

    op.drop_constraint(
        "ck_ledger_reversal_reference",
        "ledger_entries",
        type_="check",
    )

    op.drop_constraint(
        "ck_ledger_entry_type",
        "ledger_entries",
        type_="check",
    )

    # Restore the original allowed entry types.
    op.create_check_constraint(
        "ck_ledger_entry_type",
        "ledger_entries",
        "entry_type IN "
        "('deposit', 'withdrawal', 'realized_pnl', 'commission', 'swap')",
    )

    op.drop_constraint(
        "fk_ledger_entries_reversal_of_id",
        "ledger_entries",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_ledger_entries_reversal_of_id",
        "ledger_entries",
        type_="unique",
    )

    op.drop_column("ledger_entries", "reversal_of_id")
