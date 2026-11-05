import unittest
from unittest.mock import AsyncMock, patch

from app.domains.portfolio.services.account_service import (
    AccountNotFoundError,
    AccountValidationError,
    create_account,
    get_account,
)


class AccountServiceTests(unittest.IsolatedAsyncioTestCase):

    @patch(
        "app.domains.portfolio.services.account_service.account_repository.create_account",
        new_callable=AsyncMock,
    )
    async def test_creates_account_with_normalized_values(
        self, mock_create
    ):
        expected = object()
        mock_create.return_value = expected

        result = await create_account(
            AsyncMock(),
            name="  Main Trading Account  ",
            currency="usd",
        )

        self.assertIs(result, expected)
        mock_create.assert_awaited_once()

        kwargs = mock_create.await_args.kwargs
        self.assertEqual(kwargs["name"], "Main Trading Account")
        self.assertEqual(kwargs["currency"], "USD")

    async def test_rejects_empty_account_name(self):
        with self.assertRaises(AccountValidationError):
            await create_account(
                AsyncMock(),
                name="   ",
            )

    async def test_rejects_account_name_over_100_characters(self):
        with self.assertRaises(AccountValidationError):
            await create_account(
                AsyncMock(),
                name="A" * 101,
            )

    async def test_rejects_invalid_currency(self):
        with self.assertRaises(AccountValidationError):
            await create_account(
                AsyncMock(),
                name="Main",
                currency="EURO",
            )

    async def test_rejects_non_ascii_currency(self):
        with self.assertRaises(AccountValidationError):
            await create_account(
                AsyncMock(),
                name="Main",
                currency="ÉUR",
            )

    @patch(
        "app.domains.portfolio.services.account_service.account_repository.get_account",
        new_callable=AsyncMock,
    )
    async def test_get_account_returns_existing_account(
        self, mock_get
    ):
        expected = object()
        mock_get.return_value = expected

        result = await get_account(
            AsyncMock(),
            account_id=1,
        )

        self.assertIs(result, expected)

    @patch(
        "app.domains.portfolio.services.account_service.account_repository.get_account",
        new_callable=AsyncMock,
    )
    async def test_get_account_rejects_missing_account(
        self, mock_get
    ):
        mock_get.return_value = None

        with self.assertRaises(AccountNotFoundError):
            await get_account(
                AsyncMock(),
                account_id=999999,
            )

    async def test_rejects_boolean_account_id(self):
        with self.assertRaises(AccountValidationError):
            await get_account(
                AsyncMock(),
                account_id=True,
            )


if __name__ == "__main__":
    unittest.main()
