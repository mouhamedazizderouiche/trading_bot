import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routes import accounts as accounts_route
from app.domains.portfolio.models import TradingAccount
from app.infrastructure.database.session import get_db
from app.main import app


# Never allow API tests to use the development database.
base_url = make_url(os.environ["DATABASE_URL"])

if base_url.database not in ("trading", "xau_trading_test"):
    raise RuntimeError(
        "Unexpected DATABASE_URL database. Refusing to run API tests."
    )

test_url = base_url.set(database="xau_trading_test")


class AccountAPITests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(
            test_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )

        self.TestSession = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

        async def override_get_db():
            async with self.TestSession() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_create_account_and_persist(self):
        name = f"API test {uuid4().hex}"

        response = await self.client.post(
            "/api/v1/accounts",
            json={"name": name, "currency": "USD"},
        )

        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["name"], name)
        self.assertEqual(data["currency"], "USD")
        self.assertIsInstance(data["id"], int)

        async with self.TestSession() as session:
            account = await session.get(TradingAccount, data["id"])

            self.assertIsNotNone(account)
            self.assertEqual(account.name, name)

    async def test_list_accounts(self):
        name = f"API list {uuid4().hex}"

        create_response = await self.client.post(
            "/api/v1/accounts",
            json={"name": name, "currency": "USD"},
        )
        self.assertEqual(create_response.status_code, 201)

        response = await self.client.get("/api/v1/accounts")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(account["name"] == name for account in response.json())
        )

    async def test_get_existing_account(self):
        name = f"API get {uuid4().hex}"

        create_response = await self.client.post(
            "/api/v1/accounts",
            json={"name": name, "currency": "USD"},
        )
        account_id = create_response.json()["id"]

        response = await self.client.get(
            f"/api/v1/accounts/{account_id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], account_id)
        self.assertEqual(response.json()["name"], name)

    async def test_missing_account_returns_404(self):
        response = await self.client.get(
            "/api/v1/accounts/2147483647"
        )

        self.assertEqual(response.status_code, 404)

    async def test_out_of_range_account_id_returns_422(self):
        response = await self.client.get(
            "/api/v1/accounts/2147483648"
        )

        self.assertEqual(response.status_code, 422)

    async def test_invalid_account_input_returns_422(self):
        response = await self.client.post(
            "/api/v1/accounts",
            json={"name": "", "currency": "USD"},
        )

        self.assertEqual(response.status_code, 422)

    async def test_failed_creation_rolls_back_transaction(self):
        name = f"API rollback {uuid4().hex}"

        original_create = accounts_route.create_account

        async def create_then_fail(session, *, name, currency):
            await original_create(
                session,
                name=name,
                currency=currency,
            )
            raise RuntimeError("Simulated failure")

        transport = ASGITransport(
            app=app,
            raise_app_exceptions=False,
        )

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            with patch.object(
                accounts_route,
                "create_account",
                new=create_then_fail,
            ):
                response = await client.post(
                    "/api/v1/accounts",
                    json={"name": name, "currency": "USD"},
                )

        self.assertEqual(response.status_code, 500)

        async with self.TestSession() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(TradingAccount)
                .where(TradingAccount.name == name)
            )

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
