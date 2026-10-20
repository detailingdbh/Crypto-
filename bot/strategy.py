"""Trading rules: EMA crossover with trend and RSI filters, ATR-based stop loss / take profit.

Candles are ccxt OHLCV rows: [timestamp_ms, open, high, low, close, volume], closed candles only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig, StrategyConfig
from .indicators import atr, ema, rsi


@dataclass
class Signal:
    action: str  # "buy", "sell" or "hold"
    reason: str


@dataclass
class Analysis:
    close: float
    ema_fast: float
    ema_slow: float
    trend: float | None
    rsi: float
    atr: float
    crossed_up: bool
    crossed_down: bool


def analyze(candles: list[list[float]], cfg: StrategyConfig) -> Analysis | None:
    """Compute indicators on the last closed candle, or None if there is not enough history."""
    needed = max(cfg.ema_slow, cfg.trend_ema, cfg.rsi_period, cfg.atr_period) + 2
    if len(candles) < needed:
        return None
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    fast = ema(closes, cfg.ema_fast)
    slow = ema(closes, cfg.ema_slow)
    trend = ema(closes, cfg.trend_ema)[-1] if cfg.trend_ema > 0 else None
    r = rsi(closes, cfg.rsi_period)[-1]
    a = atr(highs, lows, closes, cfg.atr_period)[-1]
    if None in (fast[-2], slow[-2], fast[-1], slow[-1], r, a) or (cfg.trend_ema > 0 and trend is None):
        return None
    return Analysis(
        close=closes[-1],
        ema_fast=fast[-1],
        ema_slow=slow[-1],
        trend=trend,
        rsi=r,
        atr=a,
        crossed_up=fast[-2] <= slow[-2] and fast[-1] > slow[-1],
        crossed_down=fast[-2] >= slow[-2] and fast[-1] < slow[-1],
    )


def entry_signal(a: Analysis | None, cfg: StrategyConfig) -> Signal:
    if a is None:
        return Signal("hold", "pas assez d'historique")
    if not a.crossed_up:
        return Signal("hold", "pas de croisement haussier")
    if a.trend is not None and a.close <= a.trend:
        return Signal("hold", f"sous la tendance EMA{cfg.trend_ema}")
    if a.rsi >= cfg.rsi_max_buy:
        return Signal("hold", f"RSI trop haut ({a.rsi:.1f})")
    return Signal("buy", f"croisement EMA{cfg.ema_fast}/EMA{cfg.ema_slow} haussier, RSI {a.rsi:.1f}")


def exit_signal(a: Analysis | None, price: float, stop: float, take_profit: float) -> Signal:
    if price <= stop:
        return Signal("sell", f"stop loss touché ({price:.6g} <= {stop:.6g})")
    if price >= take_profit:
        return Signal("sell", f"take profit touché ({price:.6g} >= {take_profit:.6g})")
    if a is not None and a.crossed_down:
        return Signal("sell", "croisement EMA baissier")
    return Signal("hold", "position conservée")


def stop_levels(entry_price: float, atr_value: float, cfg: RiskConfig) -> tuple[float, float]:
    return entry_price - cfg.stop_loss_atr * atr_value, entry_price + cfg.take_profit_atr * atr_value
