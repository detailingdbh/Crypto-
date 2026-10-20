from bot.config import Config, RiskConfig, StrategyConfig

HOUR = 3_600_000


def small_config(tmp_path, **risk) -> Config:
    cfg = Config(
        exchange="binance",
        symbols=["BTC/EUR"],
        timeframe="1h",
        candles=60,
        poll_seconds=5,
        strategy=StrategyConfig(ema_fast=3, ema_slow=6, trend_ema=0, rsi_period=5, rsi_max_buy=101, atr_period=5),
        risk=RiskConfig(**{"quote_per_trade": 100, "max_open_positions": 2, "stop_loss_atr": 2,
                           "take_profit_atr": 4, "max_daily_loss": 50, "max_trades_per_day": 10, **risk}),
        data_dir=str(tmp_path),
    )
    cfg.validate()
    return cfg


def candles_from_closes(closes, start_ts=0, spread=1.0):
    return [[start_ts + i * HOUR, c, c + spread, c - spread, c, 1.0] for i, c in enumerate(closes)]


def uptrend_cross():
    """Falling prices then a sharp rebound: the fast EMA crosses above the slow one on the last candle."""
    closes = [100 - i for i in range(30)]
    closes.append(closes[-1] + 15)
    return closes
