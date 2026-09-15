import pytest

from kestrel.finance import CASH, Ledger


def test_unknown_category_rejected():
    l = Ledger(0.0)
    with pytest.raises(ValueError):
        l.post(0, "COGS", -100.0)


def test_cash_moves_only_on_cash_categories():
    l = Ledger(1000.0)
    l.post(0, "deposit", -300.0, "PO-0001")
    l.post(1, "revenue", 500.0, "AR-0001")          # accrual, no cash yet
    l.post(2, "customer_receipt", 500.0, "AR-0001")
    assert l.cash == 1200.0


def test_pnl_and_holding():
    l = Ledger(0.0)
    l.post(0, "revenue", 1000.0); l.post(0, "cogs_components", -300.0); l.post(0, "chargebacks", -30.0)
    l.holding_charge(0, 365000.0)
    p = l.pnl(0)
    assert p["revenue"] == 1000.0 and p["cogs"] == -300.0 and p["holding"] == -250.0
    assert p["operating_result"] == 1000 - 300 - 30 - 250


def test_working_capital():
    wc = Ledger(0.0).working_capital(90, receivables=90000, payables=45000, inventory_value=180000, revenue_90d=270000, cogs_90d=180000)
    assert wc["dso"] == 30 and wc["dpo"] == 22.5 and wc["dio"] == 90 and wc["ccc"] == 97.5


def test_operating_expense_is_accrued_and_paid_once():
    ledger = Ledger(1000.0)
    ledger.post(2, "freight", -125.0, "BK-0001")
    assert ledger.total("freight") == -125.0
    assert ledger.total("operating_payment") == -125.0
    assert ledger.cash == 875.0
    assert ledger.cash == ledger.opening_cash + sum(a for _, c, a, _ in ledger.lines if c in CASH)
