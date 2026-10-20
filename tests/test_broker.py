import ccxt
import pytest

from bot.broker import OrderRejected, PaperBroker, with_retry


def test_paper_buy_and_sell_with_fees():
    balances = {"EUR": 1000.0}
    b = PaperBroker(market=None, balances=balances, fee_rate=0.01)
    fill = b.buy("BTC/EUR", 100, price=50)
    assert fill.amount == pytest.approx(1.98)
    assert balances["EUR"] == pytest.approx(900)
    sell = b.sell("BTC/EUR", fill.amount, price=60)
    assert sell.quote == pytest.approx(1.98 * 60 * 0.99)
    assert balances["BTC"] == pytest.approx(0)
    assert balances["EUR"] == pytest.approx(900 + sell.quote)


def test_paper_rejects_insufficient_balance():
    b = PaperBroker(market=None, balances={"EUR": 10.0}, fee_rate=0)
    with pytest.raises(OrderRejected):
        b.buy("BTC/EUR", 100, price=50)
    with pytest.raises(OrderRejected):
        b.sell("BTC/EUR", 1, price=50)


def test_with_retry_recovers_from_network_error():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ccxt.NetworkError("down")
        return "ok"

    assert with_retry(flaky, sleep=lambda s: None) == "ok"
    assert len(calls) == 3


def test_with_retry_gives_up():
    def broken():
        raise ccxt.NetworkError("down")

    with pytest.raises(ccxt.NetworkError):
        with_retry(broken, attempts=2, sleep=lambda s: None)


def test_with_retry_does_not_retry_other_errors():
    calls = []

    def bad():
        calls.append(1)
        raise ccxt.InsufficientFunds("no")

    with pytest.raises(ccxt.InsufficientFunds):
        with_retry(bad, sleep=lambda s: None)
    assert len(calls) == 1


class FakeExchange:
    def __init__(self, order, free=None):
        self.order = order
        self.free = free or {}
        self.created = []

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.4f}"

    def market(self, symbol):
        return {"limits": {"amount": {"min": 0.0001}, "cost": {"min": 5}}}

    def create_order(self, symbol, type_, side, amount):
        self.created.append((side, amount))
        return self.order

    def fetch_balance(self):
        return {"free": self.free}


def make_live(order, free=None):
    from bot.broker import LiveBroker

    b = LiveBroker.__new__(LiveBroker)  # skip load_markets (no network in tests)
    b.ex = FakeExchange(order, free)
    return b


def test_live_buy_subtracts_base_fee():
    b = make_live({"id": "1", "filled": 0.002, "average": 50000, "cost": 100,
                   "fee": {"currency": "BTC", "cost": 0.000002}})
    fill = b.buy("BTC/EUR", 100, price=50000)
    assert b.ex.created == [("buy", 0.002)]
    assert fill.amount == pytest.approx(0.001998)
    assert fill.quote == pytest.approx(100)


def test_live_sell_caps_to_free_balance_and_deducts_quote_fee():
    b = make_live({"id": "2", "filled": 0.0019, "average": 60000, "cost": 114,
                   "fee": {"currency": "EUR", "cost": 0.5}}, free={"BTC": 0.0019})
    fill = b.sell("BTC/EUR", 0.002, price=60000)
    assert b.ex.created == [("sell", 0.0019)]
    assert fill.quote == pytest.approx(113.5)


def test_live_rejects_too_small_order():
    b = make_live({})
    with pytest.raises(OrderRejected):
        b.buy("BTC/EUR", 2, price=50000)
