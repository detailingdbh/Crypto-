"""Test the strategy on past prices before risking money.

    python backtest.py --symbol BTC/EUR --days 180
    python backtest.py --csv historique.csv   # colonnes: timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, field

from bot.broker import make_exchange, with_retry
from bot.config import Config, ConfigError, load_config
from bot.strategy import analyze, entry_signal, exit_signal, stop_levels


@dataclass
class Result:
    start_balance: float
    end_balance: float
    trades: list[float] = field(default_factory=list)  # pnl per trade
    max_drawdown: float = 0.0
    buy_and_hold: float = 0.0

    def report(self) -> str:
        wins = [p for p in self.trades if p > 0]
        ret = (self.end_balance / self.start_balance - 1) * 100
        lines = [
            f"Solde : {self.start_balance:.2f} -> {self.end_balance:.2f} ({ret:+.2f} %)",
            f"Trades : {len(self.trades)} | gagnants : {len(wins)}"
            + (f" ({len(wins) / len(self.trades) * 100:.0f} %)" if self.trades else ""),
            f"Pire baisse (drawdown max) : {self.max_drawdown * 100:.2f} %",
            f"Acheter et garder sur la période : {self.buy_and_hold * 100:+.2f} %",
        ]
        return "\n".join(lines)


def run_backtest(candles: list[list[float]], cfg: Config) -> Result:
    """Decide on each candle close, execute at the next candle open; SL/TP trigger intrabar."""
    fee = cfg.paper.fee_rate
    balance = cfg.paper.starting_balance
    res = Result(start_balance=balance, end_balance=balance)
    pos = None  # (amount, cost, stop, take_profit)
    peak = balance
    warmup = max(cfg.strategy.ema_slow, cfg.strategy.trend_ema, cfg.strategy.rsi_period, cfg.strategy.atr_period) + 2
    pending: str | None = None
    pending_atr = 0.0

    for i in range(warmup, len(candles)):
        _, open_, high, low, close, _ = candles[i][:6]

        if pending == "buy" and pos is None and balance >= cfg.risk.quote_per_trade:
            cost = cfg.risk.quote_per_trade
            amount = cost * (1 - fee) / open_
            stop, tp = stop_levels(open_, pending_atr, cfg.risk)
            balance -= cost
            pos = (amount, cost, stop, tp)
        elif pending == "sell" and pos is not None:
            balance, pos = _close(res, balance, pos, open_, fee), None
        pending = None

        if pos is not None:
            _, _, stop, tp = pos
            if low <= stop:
                balance, pos = _close(res, balance, pos, min(stop, open_), fee), None
            elif high >= tp:
                balance, pos = _close(res, balance, pos, max(tp, open_), fee), None

        a = analyze(candles[max(0, i + 1 - cfg.candles) : i + 1], cfg.strategy)
        if pos is None:
            if entry_signal(a, cfg.strategy).action == "buy":
                pending, pending_atr = "buy", a.atr
        elif exit_signal(a, close, pos[2], pos[3]).action == "sell":
            pending = "sell"

        equity = balance + (pos[0] * close if pos else 0)
        peak = max(peak, equity)
        res.max_drawdown = max(res.max_drawdown, (peak - equity) / peak)

    if pos is not None:
        balance = _close(res, balance, pos, candles[-1][4], fee)
    res.end_balance = balance
    res.buy_and_hold = candles[-1][4] / candles[warmup][1] - 1 if len(candles) > warmup else 0.0
    return res


def _close(res: Result, balance: float, pos, price: float, fee: float) -> float:
    amount, cost, _, _ = pos
    proceeds = amount * price * (1 - fee)
    res.trades.append(proceeds - cost)
    return balance + proceeds


def download(cfg: Config, symbol: str, days: int) -> list[list[float]]:
    ex = make_exchange(cfg.exchange)
    with_retry(ex.load_markets)
    tf_ms = ex.parse_timeframe(cfg.timeframe) * 1000
    since = int(time.time() * 1000) - days * 86_400_000
    out: list[list[float]] = []
    while True:
        batch = with_retry(lambda: ex.fetch_ohlcv(symbol, cfg.timeframe, since=since, limit=1000))
        if not batch:
            break
        out.extend(c for c in batch if not out or c[0] > out[-1][0])
        if batch[-1][0] + tf_ms >= time.time() * 1000 or len(batch) < 2:
            break
        since = batch[-1][0] + tf_ms
    return out


def load_csv(path: str) -> list[list[float]]:
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and r[0][0].isdigit()]
    return [[float(x) for x in r[:6]] for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest de la stratégie")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--symbol", help="paire à tester (défaut : toutes celles de la config)")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--csv", help="fichier CSV de bougies au lieu du téléchargement")
    args = p.parse_args()
    try:
        cfg = load_config(args.config)
    except (ConfigError, TypeError) as e:
        print(f"Configuration invalide : {e}", file=sys.stderr)
        return 2

    if args.csv:
        datasets = {args.csv: load_csv(args.csv)}
    else:
        symbols = [args.symbol] if args.symbol else cfg.symbols
        datasets = {s: download(cfg, s, args.days) for s in symbols}
    for name, candles in datasets.items():
        print(f"\n=== {name} ({len(candles)} bougies {cfg.timeframe}) ===")
        print(run_backtest(candles, cfg).report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
