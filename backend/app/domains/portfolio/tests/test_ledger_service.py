import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.domains.portfolio.services.ledger_service import (
    IdempotencyConflictError,
    _validate_positive_amount,
    record_deposit,
    record_withdrawal,
)


class TestLedgerValidation(unittest.TestCase):

    def test_rejects_float(self):
        with self.assertRaises(TypeError):
            _validate_positive_amount(10.50)

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            _validate_positive_amount(Decimal("0"))

    def test_rejects_negative_amount(self):
        with self.assertRaises(ValueError):
            _validate_positive_amount(Decimal("-10"))

    def test_rejects_nan(self):
        with self.assertRaises(ValueError):
            _validate_positive_amount(Decimal("NaN"))

    def test_rejects_infinity(self):
        with self.assertRaises(ValueError):
            _validate_positive_amount(Decimal("Infinity"))

    def test_rejects_more_than_eight_decimal_places(self):
        with self.assertRaises(ValueError):
            _validate_positive_amount(Decimal("10.123456789"))

    def test_accepts_valid_amount(self):
        _validate_positive_amount(Decimal("100.12345678"))


class TestLedgerOperations(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.account = SimpleNamespace(currency="USD")
        self.session = Mock()
        self.session.get = AsyncMock(return_value=self.account)
        self.session.scalar = AsyncMock(return_value=None)

        insert_result = Mock()
        insert_result.scalar_one_or_none.return_value = 42
        self.session.execute = AsyncMock(return_value=insert_result)

    async def test_deposit_is_positive(self):
        expected = SimpleNamespace(
            amount=Decimal("100"),
            entry_type="deposit",
        )
        self.session.get = AsyncMock(
            side_effect=[self.account, expected]
        )

        entry = await record_deposit(
            self.session,
            account_id=1,
            amount=Decimal("100"),
            currency="USD",
            idempotency_key="deposit-001",
        )

        self.assertEqual(entry.amount, Decimal("100"))
        self.assertEqual(entry.entry_type, "deposit")
        self.session.execute.assert_awaited_once()

    async def test_withdrawal_is_negative(self):
        expected = SimpleNamespace(
            amount=Decimal("-25"),
            entry_type="withdrawal",
        )
        self.session.get = AsyncMock(
            side_effect=[self.account, expected]
        )

        entry = await record_withdrawal(
            self.session,
            account_id=1,
            amount=Decimal("25"),
            currency="USD",
            idempotency_key="withdrawal-001",
        )

        self.assertEqual(entry.amount, Decimal("-25"))
        self.assertEqual(entry.entry_type, "withdrawal")
        self.session.execute.assert_awaited_once()

    async def test_duplicate_request_returns_existing_entry(self):
        existing = SimpleNamespace(
            account_id=1,
            entry_type="deposit",
            amount=Decimal("100"),
            currency="USD",
            reference=None,
        )

        conflict_result = Mock()
        conflict_result.scalar_one_or_none.return_value = None
        self.session.execute = AsyncMock(return_value=conflict_result)
        self.session.scalar = AsyncMock(return_value=existing)

        result = await record_deposit(
            self.session,
            account_id=1,
            amount=Decimal("100"),
            currency="USD",
            idempotency_key="deposit-001",
        )

        self.assertIs(result, existing)

    async def test_reused_key_with_different_amount_is_rejected(self):
        existing = SimpleNamespace(
            account_id=1,
            entry_type="deposit",
            amount=Decimal("100"),
            currency="USD",
            reference=None,
        )

        conflict_result = Mock()
        conflict_result.scalar_one_or_none.return_value = None
        self.session.execute = AsyncMock(return_value=conflict_result)
        self.session.scalar = AsyncMock(return_value=existing)

        with self.assertRaises(IdempotencyConflictError):
            await record_deposit(
                self.session,
                account_id=1,
                amount=Decimal("200"),
                currency="USD",
                idempotency_key="deposit-001",
            )


if __name__ == "__main__":
    unittest.main()
