import asyncio
import os
import unittest
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domains.portfolio.models.account import TradingAccount
from app.domains.portfolio.models.ledger_entry import LedgerEntry
from app.domains.portfolio.services.ledger_service import (
    IdempotencyConflictError,
    ReversalConflictError,
    get_cash_balance,
    record_deposit,
    record_reversal,
    record_withdrawal,
)


# Never allow integration tests to connect to the development database.
base_url = make_url(os.environ["DATABASE_URL"])

if base_url.database not in ("trading", "xau_trading_test"):
    raise RuntimeError(
        "Unexpected DATABASE_URL database. Refusing to run integration tests."
    )

test_url = base_url.set(database="xau_trading_test")

engine = create_async_engine(
    test_url,
    pool_pre_ping=True,
    poolclass=NullPool,
)

TestSession = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


class PostgreSQLLedgerTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.account_id = None
        self.key = uuid4().hex

        async with TestSession() as session:
            account = TradingAccount(
                name=f"Integration test {self.key[:12]}",
                currency="USD",
            )
            session.add(account)
            await session.commit()
            self.account_id = account.id

    async def asyncTearDown(self):
        # Ledger entries are immutable.
        # Each test creates its own account and retains its records.
        pass
    async def test_deposit_is_persisted(self):
        async with TestSession() as session:
            entry = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            entry_id = entry.id

        async with TestSession() as session:
            persisted = await session.get(LedgerEntry, entry_id)

            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.amount, Decimal("100.00"))
            self.assertEqual(persisted.entry_type, "deposit")

    async def test_withdrawal_is_persisted(self):
        async with TestSession() as session:
            await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()

        async with TestSession() as session:
            withdrawal = await record_withdrawal(
                session,
                account_id=self.account_id,
                amount=Decimal("25.00"),
                currency="USD",
                idempotency_key=uuid4().hex,
            )
            await session.commit()

            self.assertEqual(withdrawal.amount, Decimal("-25.00"))

        async with TestSession() as session:
            balance = await get_cash_balance(
                session,
                account_id=self.account_id,
            )

            self.assertEqual(balance, Decimal("75.00"))

    async def test_duplicate_request_returns_existing_entry(self):
        async with TestSession() as session:
            first = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            first_id = first.id

        async with TestSession() as session:
            second = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()

            self.assertEqual(second.id, first_id)

    async def test_reused_key_with_different_data_is_rejected(self):
        async with TestSession() as session:
            await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()

        async with TestSession() as session:
            with self.assertRaises(IdempotencyConflictError):
                await record_deposit(
                    session,
                    account_id=self.account_id,
                    amount=Decimal("75.00"),
                    currency="USD",
                    idempotency_key=self.key,
                )

    async def test_concurrent_duplicate_requests_create_one_entry(self):
        async def submit_deposit():
            async with TestSession() as session:
                entry = await record_deposit(
                    session,
                    account_id=self.account_id,
                    amount=Decimal("100.00"),
                    currency="USD",
                    idempotency_key=self.key,
                )
                await session.commit()
                return entry.id

        first_id, second_id = await asyncio.gather(
            submit_deposit(),
            submit_deposit(),
        )

        self.assertEqual(first_id, second_id)

        async with TestSession() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.idempotency_key == self.key)
            )

            balance = await get_cash_balance(
                session,
                account_id=self.account_id,
            )

            self.assertEqual(count, 1)
            self.assertEqual(balance, Decimal("100.00"))



    async def test_reversal_of_deposit_restores_balance(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            original_id = original.id

        async with TestSession() as session:
            reversal = await record_reversal(
                session,
                original_entry_id=original_id,
                idempotency_key=uuid4().hex,
            )
            await session.commit()

            self.assertEqual(reversal.entry_type, "reversal")
            self.assertEqual(reversal.amount, Decimal("-100.00"))
            self.assertEqual(reversal.reversal_of_id, original_id)

        async with TestSession() as session:
            balance = await get_cash_balance(
                session,
                account_id=self.account_id,
            )
            self.assertEqual(balance, Decimal("0.00"))

    async def test_reversal_of_withdrawal_restores_balance(self):
        async with TestSession() as session:
            await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()

        async with TestSession() as session:
            withdrawal = await record_withdrawal(
                session,
                account_id=self.account_id,
                amount=Decimal("25.00"),
                currency="USD",
                idempotency_key=uuid4().hex,
            )
            await session.commit()
            withdrawal_id = withdrawal.id

        async with TestSession() as session:
            reversal = await record_reversal(
                session,
                original_entry_id=withdrawal_id,
                idempotency_key=uuid4().hex,
            )
            await session.commit()

            self.assertEqual(reversal.amount, Decimal("25.00"))

        async with TestSession() as session:
            balance = await get_cash_balance(
                session,
                account_id=self.account_id,
            )
            self.assertEqual(balance, Decimal("100.00"))

    async def test_duplicate_reversal_returns_existing_entry(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            original_id = original.id

        reversal_key = uuid4().hex

        async with TestSession() as session:
            first = await record_reversal(
                session,
                original_entry_id=original_id,
                idempotency_key=reversal_key,
                reference="correction",
            )
            await session.commit()
            first_id = first.id

        async with TestSession() as session:
            second = await record_reversal(
                session,
                original_entry_id=original_id,
                idempotency_key=reversal_key,
                reference="correction",
            )
            await session.commit()

            self.assertEqual(second.id, first_id)

    async def test_second_reversal_with_different_key_is_rejected(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            original_id = original.id

        async with TestSession() as session:
            await record_reversal(
                session,
                original_entry_id=original_id,
                idempotency_key=uuid4().hex,
            )
            await session.commit()

        async with TestSession() as session:
            with self.assertRaises(ReversalConflictError):
                await record_reversal(
                    session,
                    original_entry_id=original_id,
                    idempotency_key=uuid4().hex,
                )

    async def test_reversal_of_reversal_is_rejected(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            original_id = original.id

        async with TestSession() as session:
            reversal = await record_reversal(
                session,
                original_entry_id=original_id,
                idempotency_key=uuid4().hex,
            )
            await session.commit()
            reversal_id = reversal.id

        async with TestSession() as session:
            with self.assertRaises(ValueError):
                await record_reversal(
                    session,
                    original_entry_id=reversal_id,
                    idempotency_key=uuid4().hex,
                )

    async def test_reversal_of_missing_entry_is_rejected(self):
        async with TestSession() as session:
            with self.assertRaises(ValueError):
                await record_reversal(
                    session,
                    original_entry_id=999999999,
                    idempotency_key=uuid4().hex,
                )

    async def test_direct_update_of_ledger_entry_is_blocked(self):
        async with TestSession() as session:
            entry = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            entry_id = entry.id

        async with TestSession() as session:
            with self.assertRaises(DBAPIError):
                await session.execute(
                    text(
                        "UPDATE ledger_entries "
                        "SET reference = 'tampered' WHERE id = :entry_id"
                    ),
                    {"entry_id": entry_id},
                )
            await session.rollback()

        async with TestSession() as session:
            persisted = await session.get(LedgerEntry, entry_id)
            self.assertIsNotNone(persisted)
            self.assertIsNone(persisted.reference)

    async def test_direct_delete_of_ledger_entry_is_blocked(self):
        async with TestSession() as session:
            entry = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("50.00"),
                currency="USD",
                idempotency_key=self.key,
            )
            await session.commit()
            entry_id = entry.id

        async with TestSession() as session:
            with self.assertRaises(DBAPIError):
                await session.execute(
                    text(
                        "DELETE FROM ledger_entries "
                        "WHERE id = :entry_id"
                    ),
                    {"entry_id": entry_id},
                )
            await session.rollback()

        async with TestSession() as session:
            persisted = await session.get(LedgerEntry, entry_id)
            self.assertIsNotNone(persisted)
    async def test_concurrent_duplicate_reversals_create_one_entry(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=uuid4().hex,
            )
            await session.commit()
            original_id = original.id

        reversal_key = uuid4().hex

        async def reverse():
            async with TestSession() as session:
                entry = await record_reversal(
                    session,
                    original_entry_id=original_id,
                    idempotency_key=reversal_key,
                    reference="concurrent-same-key",
                )
                await session.commit()
                return entry.id

        first_id, second_id = await asyncio.gather(reverse(), reverse())

        self.assertEqual(first_id, second_id)

        async with TestSession() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.reversal_of_id == original_id)
            )

        self.assertEqual(count, 1)

    async def test_concurrent_reversals_with_different_keys_create_one_entry(self):
        async with TestSession() as session:
            original = await record_deposit(
                session,
                account_id=self.account_id,
                amount=Decimal("100.00"),
                currency="USD",
                idempotency_key=uuid4().hex,
            )
            await session.commit()
            original_id = original.id

        async def reverse(key):
            async with TestSession() as session:
                entry = await record_reversal(
                    session,
                    original_entry_id=original_id,
                    idempotency_key=key,
                    reference="concurrent-different-keys",
                )
                await session.commit()
                return entry.id

        results = await asyncio.gather(
            reverse(uuid4().hex),
            reverse(uuid4().hex),
            return_exceptions=True,
        )

        successful_ids = [
            result for result in results
            if isinstance(result, int)
        ]
        conflicts = [
            result for result in results
            if isinstance(result, ReversalConflictError)
        ]

        self.assertEqual(len(successful_ids), 1)
        self.assertEqual(len(conflicts), 1)

        async with TestSession() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.reversal_of_id == original_id)
            )

        self.assertEqual(count, 1)
if __name__ == "__main__":
    unittest.main()






