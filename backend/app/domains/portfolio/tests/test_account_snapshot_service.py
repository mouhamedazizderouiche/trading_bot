import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.domains.portfolio.services.account_service import (
    AccountNotFoundError,
)
from app.domains.portfolio.services.account_snapshot_service import (
    get_account_financial_snapshot,
)


class AccountSnapshotServiceTests(unittest.IsolatedAsyncioTestCase):

    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_cash_balance",
        new_callable=AsyncMock,
    )
    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_account",
        new_callable=AsyncMock,
    )
    async def test_builds_financial_snapshot(
        self,
        mock_get_account,
        mock_get_cash_balance,
    ):
        mock_get_account.return_value = SimpleNamespace(
            id=1,
            currency="USD",
        )
        mock_get_cash_balance.return_value = Decimal("1000.00")

        result = await get_account_financial_snapshot(
            AsyncMock(),
            account_id=1,
            unrealized_pnl=Decimal("50.00"),
            used_margin=Decimal("200.00"),
        )

        self.assertEqual(result.account_id, 1)
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.cash_balance, Decimal("1000.00"))
        self.assertEqual(result.unrealized_pnl, Decimal("50.00"))
        self.assertEqual(result.equity, Decimal("1050.00"))
        self.assertEqual(result.used_margin, Decimal("200.00"))
        self.assertEqual(result.free_margin, Decimal("850.00"))

        mock_get_account.assert_awaited_once()
        mock_get_cash_balance.assert_awaited_once_with(
            unittest.mock.ANY,
            account_id=1,
        )

    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_cash_balance",
        new_callable=AsyncMock,
    )
    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_account",
        new_callable=AsyncMock,
    )
    async def test_supports_negative_unrealized_pnl(
        self,
        mock_get_account,
        mock_get_cash_balance,
    ):
        mock_get_account.return_value = SimpleNamespace(
            id=1,
            currency="USD",
        )
        mock_get_cash_balance.return_value = Decimal("1000")

        result = await get_account_financial_snapshot(
            AsyncMock(),
            account_id=1,
            unrealized_pnl=Decimal("-100"),
            used_margin=Decimal("200"),
        )

        self.assertEqual(result.equity, Decimal("900"))
        self.assertEqual(result.free_margin, Decimal("700"))

    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_account",
        new_callable=AsyncMock,
    )
    async def test_rejects_missing_account(self, mock_get_account):
        mock_get_account.side_effect = AccountNotFoundError(
            "Trading account does not exist"
        )

        with self.assertRaises(AccountNotFoundError):
            await get_account_financial_snapshot(
                AsyncMock(),
                account_id=999999,
                unrealized_pnl=Decimal("0"),
                used_margin=Decimal("0"),
            )

    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_account",
        new_callable=AsyncMock,
    )
    async def test_rejects_float_unrealized_pnl(
        self,
        mock_get_account,
    ):
        mock_get_account.return_value = SimpleNamespace(
            id=1,
            currency="USD",
        )

        with self.assertRaises(TypeError):
            await get_account_financial_snapshot(
                AsyncMock(),
                account_id=1,
                unrealized_pnl=50.0,
                used_margin=Decimal("0"),
            )

    @patch(
        "app.domains.portfolio.services.account_snapshot_service.get_account",
        new_callable=AsyncMock,
    )
    async def test_rejects_negative_used_margin(
        self,
        mock_get_account,
    ):
        mock_get_account.return_value = SimpleNamespace(
            id=1,
            currency="USD",
        )

        with self.assertRaises(ValueError):
            await get_account_financial_snapshot(
                AsyncMock(),
                account_id=1,
                unrealized_pnl=Decimal("0"),
                used_margin=Decimal("-1"),
            )


if __name__ == "__main__":
    unittest.main()
