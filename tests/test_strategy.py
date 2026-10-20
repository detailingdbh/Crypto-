from bot.config import RiskConfig, StrategyConfig
from bot.strategy import analyze, entry_signal, exit_signal, stop_levels

from .helpers import candles_from_closes, uptrend_cross

CFG = StrategyConfig(ema_fast=3, ema_slow=6, trend_ema=0, rsi_period=5, rsi_max_buy=101, atr_period=5)


def test_not_enough_history_holds():
    a = analyze(candles_from_closes([1, 2, 3]), CFG)
    assert a is None
    assert entry_signal(a, CFG).action == "hold"


def test_crossover_triggers_buy():
    a = analyze(candles_from_closes(uptrend_cross()), CFG)
    assert a.crossed_up
    assert entry_signal(a, CFG).action == "buy"


def test_no_buy_without_crossover():
    a = analyze(candles_from_closes([100 - i for i in range(30)]), CFG)
    assert entry_signal(a, CFG).action == "hold"


def test_rsi_filter_blocks_buy():
    cfg = StrategyConfig(**{**CFG.__dict__, "rsi_max_buy": 50})
    a = analyze(candles_from_closes(uptrend_cross()), cfg)
    assert a.rsi >= 50
    assert entry_signal(a, cfg).action == "hold"


def test_trend_filter_blocks_buy_below_trend():
    cfg = StrategyConfig(**{**CFG.__dict__, "trend_ema": 20})
    closes = [100 - i for i in range(30)] + [79]  # small rebound, still below the trend
    a = analyze(candles_from_closes(closes), cfg)
    assert a.crossed_up
    assert a.close < a.trend
    assert entry_signal(a, cfg).action == "hold"


def test_exit_on_stop_and_take_profit():
    assert exit_signal(None, 90, stop=95, take_profit=120).action == "sell"
    assert exit_signal(None, 125, stop=95, take_profit=120).action == "sell"
    assert exit_signal(None, 100, stop=95, take_profit=120).action == "hold"


def test_exit_on_bearish_crossover():
    closes = [70 + i for i in range(30)] + [60]
    a = analyze(candles_from_closes(closes), CFG)
    assert a.crossed_down
    assert exit_signal(a, 60, stop=1, take_profit=1000).action == "sell"


def test_stop_levels():
    assert stop_levels(100, 5, RiskConfig(stop_loss_atr=2, take_profit_atr=3)) == (90, 115)
