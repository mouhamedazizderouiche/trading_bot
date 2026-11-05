from dataclasses import dataclass
from decimal import Decimal



@dataclass(frozen=True, slots=True)
class AccountMetrics:
    equity: Decimal
    used_margin: Decimal
    free_margin: Decimal



def _validate_decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")



def calculate_account_metrics(
    cash_balance: Decimal,
    unrealized_pnl: Decimal,
    used_margin: Decimal,
) -> AccountMetrics:
    """Calculate account equity and available margin."""
    _validate_decimal("cash_balance", cash_balance)
    _validate_decimal("unrealized_pnl", unrealized_pnl)
    _validate_decimal("used_margin", used_margin)

    if used_margin < Decimal("0"):
        raise ValueError("used_margin cannot be negative")

    equity = cash_balance + unrealized_pnl
    free_margin = equity - used_margin

    return AccountMetrics(
        equity=equity,
        used_margin=used_margin,
        free_margin=free_margin,
    )
