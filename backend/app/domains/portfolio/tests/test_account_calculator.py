import unittest
from decimal import Decimal

from app.domains.portfolio.services.account_calculator import calculate_account_metrics



class AccountCalculatorTests(unittest.TestCase):
    def test_calculates_equity_and_free_margin(self):
        result = calculate_account_metrics(
            Decimal("1000.00"),
            Decimal("50.00"),
            Decimal("200.00"),
        )
        self.assertEqual(result.equity, Decimal("1050.00"))
        self.assertEqual(result.free_margin, Decimal("850.00"))

    def test_supports_negative_unrealized_pnl(self):
        result = calculate_account_metrics(
            Decimal("1000"),
            Decimal("-100"),
            Decimal("200"),
        )
        self.assertEqual(result.equity, Decimal("900"))
        self.assertEqual(result.free_margin, Decimal("700"))

    def test_allows_negative_free_margin(self):
        result = calculate_account_metrics(
            Decimal("100"),
            Decimal("-20"),
            Decimal("150"),
        )
        self.assertEqual(result.free_margin, Decimal("-70"))

    def test_rejects_float_values(self):
        with self.assertRaises(TypeError):
            calculate_account_metrics(100.0, Decimal("0"), Decimal("0"))

    def test_rejects_negative_used_margin(self):
        with self.assertRaises(ValueError):
            calculate_account_metrics(
                Decimal("100"), Decimal("0"), Decimal("-10")
            )

    def test_rejects_non_finite_values(self):
        with self.assertRaises(ValueError):
            calculate_account_metrics(
                Decimal("NaN"), Decimal("0"), Decimal("0")
            )



if __name__ == "__main__":
    unittest.main()
