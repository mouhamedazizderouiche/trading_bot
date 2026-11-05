import os
import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domains.portfolio.models import LedgerEntry
from app.infrastructure.database.session import get_db
from app.main import app


# Never allow API tests to use the development database.
base_url = make_url(os.environ["DATABASE_URL"])

if base_url.database not in ("trading", "xau_trading_test"):
    raise RuntimeError(
        "Unexpected DATABASE_URL database. Refusing to run API tests."
    )

test_url = base_url.set(database="xau_trading_test")


class CashMovementsAPITests(unittest.IsolatedAsyncioTestCase):

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

        response = await self.client.post(
            "/api/v1/accounts",
            json={
                "name": f"Cash API test {uuid4().hex}",
                "currency": "USD",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.account_id = response.json()["id"]

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_deposit_persists_and_updates_balance(self):
        response = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json={"amount": "100.00", "reference": "Initial funding"},
            headers={"Idempotency-Key": f"deposit-{uuid4().hex}"},
        )

        self.assertEqual(response.status_code, 201)
        entry = response.json()

        self.assertEqual(entry["account_id"], self.account_id)
        self.assertEqual(entry["entry_type"], "deposit")
        self.assertEqual(entry["currency"], "USD")

        balance_response = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/balance"
        )

        self.assertEqual(balance_response.status_code, 200)
        self.assertEqual(
            balance_response.json()["cash_balance"],
            "100.00000000",
        )

        async with self.TestSession() as session:
            persisted = await session.get(LedgerEntry, entry["id"])

        self.assertIsNotNone(persisted)
        self.assertEqual(str(persisted.amount), "100.00000000")

    async def test_withdrawal_records_negative_amount(self):
        response = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/withdrawals",
            json={"amount": "25.00", "reference": "Test withdrawal"},
            headers={"Idempotency-Key": f"withdrawal-{uuid4().hex}"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["entry_type"], "withdrawal")
        self.assertEqual(response.json()["amount"], "-25.00000000")

        balance_response = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/balance"
        )

        self.assertEqual(balance_response.status_code, 200)
        self.assertEqual(
            balance_response.json()["cash_balance"],
            "-25.00000000",
        )

    async def test_idempotent_deposit_replay_does_not_duplicate_entry(self):
        key = f"replay-{uuid4().hex}"
        payload = {"amount": "50.00", "reference": "Retry test"}
        headers = {"Idempotency-Key": key}

        first = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json=payload,
            headers=headers,
        )
        second = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json=payload,
            headers=headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])

        balance = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/balance"
        )
        self.assertEqual(
            balance.json()["cash_balance"],
            "50.00000000",
        )

        async with self.TestSession() as session:
            entries = await session.scalars(
                select(LedgerEntry).where(
                    LedgerEntry.account_id == self.account_id
                )
            )

        self.assertEqual(len(list(entries.all())), 1)

    async def test_reusing_idempotency_key_with_different_amount_returns_409(self):
        key = f"conflict-{uuid4().hex}"
        headers = {"Idempotency-Key": key}

        first = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json={"amount": "50.00"},
            headers=headers,
        )
        second = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json={"amount": "75.00"},
            headers=headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)

        balance = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/balance"
        )
        self.assertEqual(
            balance.json()["cash_balance"],
            "50.00000000",
        )

    async def test_transaction_history_is_paginated(self):
        for amount in ("10.00", "20.00", "30.00"):
            response = await self.client.post(
                f"/api/v1/accounts/{self.account_id}/deposits",
                json={"amount": amount},
                headers={"Idempotency-Key": f"page-{uuid4().hex}"},
            )
            self.assertEqual(response.status_code, 201)

        first_page = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/transactions",
            params={"page": 1, "page_size": 2},
        )

        self.assertEqual(first_page.status_code, 200)
        data = first_page.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 2)
        self.assertEqual(len(data["items"]), 2)

        second_page = await self.client.get(
            f"/api/v1/accounts/{self.account_id}/transactions",
            params={"page": 2, "page_size": 2},
        )

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.json()["total"], 3)
        self.assertEqual(len(second_page.json()["items"]), 1)

    async def test_missing_idempotency_key_returns_422(self):
        response = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json={"amount": "10.00"},
        )

        self.assertEqual(response.status_code, 422)

    async def test_invalid_amount_returns_422(self):
        response = await self.client.post(
            f"/api/v1/accounts/{self.account_id}/deposits",
            json={"amount": "0"},
            headers={"Idempotency-Key": f"invalid-{uuid4().hex}"},
        )

        self.assertEqual(response.status_code, 422)

    async def test_missing_account_returns_404(self):
        response = await self.client.post(
            "/api/v1/accounts/2147483647/deposits",
            json={"amount": "10.00"},
            headers={"Idempotency-Key": f"missing-{uuid4().hex}"},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
