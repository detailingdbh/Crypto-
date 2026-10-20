import ccxt
import pytest

from backtest import run_backtest
from bot.broker import PaperBroker
from bot.notify import Notifier
from bot.runner import Bot
from bot.state import StateStore

from .helpers import HOUR, candles_from_closes, small_config, uptrend_cross


class FakeMarket:
    def __init__(self, candles, price):
        self.candles = candles
        self.price = price
        self.fail = None

    def fetch_ohlcv(self, symbol, timeframe, limit):
        if self.fail:
            raise self.fail
        return self.candles[-limit:]

    def fetch_price(self, symbol):
        return self.price


def make_bot(tmp_path, closes, price, **risk):
    cfg = small_config(tmp_path, **risk)
    candles = candles_from_closes(closes)
    market = FakeMarket(candles, price)
    store = StateStore(tmp_path / "state.json")
    state = store.load()
    state.paper_balances = {"EUR": 1000.0}
    broker = PaperBroker(market, state.paper_balances, fee_rate=0.0)
    now = [candles[-1][0] / 1000 + 3600 + 1]  # last candle is closed
    bot = Bot(cfg, broker, store, state, Notifier(), clock=lambda: now[0])
    return bot, market, now


def test_buys_on_signal_and_persists(tmp_path):
    bot, _, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    bot.tick()
    pos = bot.state.positions["BTC/EUR"]
    assert pos.cost == 100
    assert pos.stop < 85 < pos.take_profit
    reloaded = StateStore(tmp_path / "state.json").load()
    assert "BTC/EUR" in reloaded.positions
    assert reloaded.paper_balances["EUR"] == pytest.approx(900)


def test_stop_loss_sells_and_does_not_rebuy_same_candle(tmp_path):
    bot, market, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    bot.tick()
    stop = bot.state.positions["BTC/EUR"].stop
    market.price = stop - 1
    bot.tick()
    assert "BTC/EUR" not in bot.state.positions
    assert bot.state.daily_pnl < 0
    market.price = 85
    bot.tick()  # same crossover candle: must not buy again
    assert "BTC/EUR" not in bot.state.positions
    assert bot.state.trades_today == 1


def test_forming_candle_is_ignored(tmp_path):
    bot, _, now = make_bot(tmp_path, uptrend_cross(), price=85)
    now[0] -= 3600  # the crossover candle is still open
    bot.tick()
    assert bot.state.positions == {}


def test_daily_loss_limit_blocks_buys(tmp_path):
    bot, _, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    bot.state.roll_day("1970-01-02")
    bot.state.daily_pnl = -60
    bot.tick()
    assert bot.state.positions == {}


def test_daily_counters_reset_next_day(tmp_path):
    bot, _, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    bot.state.day = "1969-12-31"
    bot.state.daily_pnl = -60
    bot.tick()
    assert bot.state.day == "1970-01-02"
    assert bot.state.daily_pnl == 0
    assert "BTC/EUR" in bot.state.positions


def test_kill_switch_blocks_buys(tmp_path):
    bot, _, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    (tmp_path / "STOP").touch()
    bot.tick()
    assert bot.state.positions == {}


def test_insufficient_balance_blocks_buys(tmp_path):
    bot, _, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    bot.broker.balances["EUR"] = 50
    bot.tick()
    assert bot.state.positions == {}


def test_network_error_does_not_crash(tmp_path):
    bot, market, _ = make_bot(tmp_path, uptrend_cross(), price=85)
    market.fail = ccxt.NetworkError("down")
    bot.tick()
    market.fail = RuntimeError("bug")
    bot.tick()
    market.fail = None
    bot.tick()
    assert "BTC/EUR" in bot.state.positions


def test_backtest_runs_and_accounts_balance(tmp_path):
    cfg = small_config(tmp_path)
    closes = []
    for cycle in range(6):
        closes += [100 - i for i in range(15)] + [85 + 2 * i for i in range(15)]
    res = run_backtest(candles_from_closes(closes), cfg)
    assert res.trades
    assert res.end_balance == pytest.approx(res.start_balance + sum(res.trades))
    assert 0 <= res.max_drawdown < 1
    assert "Solde" in res.report()
