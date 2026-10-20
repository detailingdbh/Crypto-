"""Main loop: analyze every symbol, manage positions, never crash on a single error."""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import ccxt

from .broker import Broker, OrderRejected
from .config import Config
from .notify import Notifier
from .state import Position, State, StateStore
from .strategy import analyze, entry_signal, exit_signal, stop_levels

log = logging.getLogger(__name__)

ERROR_NOTIFY_INTERVAL = 900  # seconds between two error notifications


class Bot:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        store: StateStore,
        state: State,
        notifier: Notifier,
        clock: Callable[[], float] = time.time,
    ):
        self.cfg = cfg
        self.broker = broker
        self.store = store
        self.state = state
        self.notifier = notifier
        self.clock = clock
        self.stop_file = Path(cfg.data_dir) / "STOP"
        self.timeframe_ms = ccxt.Exchange.parse_timeframe(cfg.timeframe) * 1000
        self._running = True
        self._last_error_notify = 0.0

    # ---- loop -------------------------------------------------------------

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self.notifier.send(
            f"🤖 Bot démarré en mode {self.cfg.mode.upper()} sur {self.cfg.exchange} : {', '.join(self.cfg.symbols)}"
        )
        while self._running:
            started = self.clock()
            try:
                self.tick()
            except Exception as e:
                log.exception("erreur inattendue dans la boucle")
                self._notify_error(f"⚠️ Erreur : {e}")
            remaining = self.cfg.poll_seconds - (self.clock() - started)
            end = time.monotonic() + max(remaining, 0)
            while self._running and time.monotonic() < end:
                time.sleep(min(1.0, end - time.monotonic()))
        self.store.save(self.state)
        self.notifier.send("🛑 Bot arrêté proprement")

    def _handle_signal(self, *_):
        log.info("signal d'arrêt reçu")
        self._running = False

    def tick(self) -> None:
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        self.state.roll_day(now.strftime("%Y-%m-%d"))
        for symbol in self.cfg.symbols:
            try:
                self.process(symbol)
            except (ccxt.NetworkError, ccxt.RateLimitExceeded) as e:
                log.warning("%s : réseau indisponible (%s), réessai au prochain tour", symbol, e)
            except Exception as e:
                log.exception("%s : erreur", symbol)
                self._notify_error(f"⚠️ {symbol} : {e}")
            finally:
                self.store.save(self.state)

    # ---- per symbol -------------------------------------------------------

    def process(self, symbol: str) -> None:
        candles = self._closed_candles(self.broker.fetch_ohlcv(symbol, self.cfg.timeframe, self.cfg.candles))
        analysis = analyze(candles, self.cfg.strategy)
        price = self.broker.fetch_price(symbol)
        pos = self.state.positions.get(symbol)
        if pos:
            sig = exit_signal(analysis, price, pos.stop, pos.take_profit)
            if sig.action == "sell":
                self._close(pos, price, sig.reason)
            else:
                log.info("%s : %.6g | position ouverte (SL %.6g / TP %.6g)", symbol, price, pos.stop, pos.take_profit)
            return

        sig = entry_signal(analysis, self.cfg.strategy)
        log.info("%s : %.6g | %s", symbol, price, sig.reason)
        if sig.action != "buy" or analysis is None:
            return
        candle_ts = int(candles[-1][0])
        if self.state.last_entry_candle.get(symbol) == candle_ts:
            return  # this crossover was already traded
        ok, why = self.can_open(symbol)
        if not ok:
            log.info("%s : achat bloqué (%s)", symbol, why)
            return
        self.state.last_entry_candle[symbol] = candle_ts
        self._open(symbol, price, analysis.atr, sig.reason)

    def _closed_candles(self, candles: list[list[float]]) -> list[list[float]]:
        now_ms = self.clock() * 1000
        if candles and candles[-1][0] + self.timeframe_ms > now_ms:
            return candles[:-1]
        return candles

    def can_open(self, symbol: str) -> tuple[bool, str]:
        r = self.cfg.risk
        if self.stop_file.exists():
            return False, f"fichier {self.stop_file} présent (arrêt d'urgence)"
        if len(self.state.positions) >= r.max_open_positions:
            return False, "nombre max de positions atteint"
        if self.state.daily_pnl <= -r.max_daily_loss:
            return False, f"perte journalière max atteinte ({self.state.daily_pnl:.2f})"
        if self.state.trades_today >= r.max_trades_per_day:
            return False, "nombre max de trades du jour atteint"
        if self.broker.quote_balance(self.cfg.quote) < r.quote_per_trade:
            return False, f"solde {self.cfg.quote} insuffisant"
        return True, ""

    def _open(self, symbol: str, price: float, atr_value: float, reason: str) -> None:
        try:
            fill = self.broker.buy(symbol, self.cfg.risk.quote_per_trade, price)
        except OrderRejected as e:
            log.warning("%s : achat refusé (%s)", symbol, e)
            return
        stop, tp = stop_levels(fill.price, atr_value, self.cfg.risk)
        pos = Position(
            symbol=symbol,
            amount=fill.amount,
            entry_price=fill.price,
            cost=fill.quote,
            stop=stop,
            take_profit=tp,
            opened_at=self._now_iso(),
        )
        self.state.positions[symbol] = pos
        self.state.trades_today += 1
        self.state.record({"time": pos.opened_at, "side": "buy", "symbol": symbol, "price": fill.price,
                           "amount": fill.amount, "quote": fill.quote, "reason": reason})
        self.store.save(self.state)
        self.notifier.send(
            f"🟢 ACHAT {symbol} : {fill.amount:.6g} à {fill.price:.6g} ({fill.quote:.2f} {self.cfg.quote})\n"
            f"Raison : {reason}\nStop loss {stop:.6g} | Take profit {tp:.6g}"
        )

    def _close(self, pos: Position, price: float, reason: str) -> None:
        try:
            fill = self.broker.sell(pos.symbol, pos.amount, price)
        except OrderRejected as e:
            log.error("%s : vente impossible (%s), position retirée du suivi", pos.symbol, e)
            self._notify_error(f"⚠️ {pos.symbol} : vente impossible ({e}). Vérifie ton compte.")
            del self.state.positions[pos.symbol]
            return
        pnl = fill.quote - pos.cost
        self.state.daily_pnl += pnl
        self.state.total_pnl += pnl
        del self.state.positions[pos.symbol]
        self.state.record({"time": self._now_iso(), "side": "sell", "symbol": pos.symbol, "price": fill.price,
                           "amount": fill.amount, "quote": fill.quote, "pnl": pnl, "reason": reason})
        self.store.save(self.state)
        emoji = "✅" if pnl >= 0 else "🔴"
        self.notifier.send(
            f"{emoji} VENTE {pos.symbol} : {fill.amount:.6g} à {fill.price:.6g}\n"
            f"Raison : {reason}\nRésultat : {pnl:+.2f} {self.cfg.quote} | "
            f"Jour : {self.state.daily_pnl:+.2f} | Total : {self.state.total_pnl:+.2f}"
        )

    # ---- helpers ----------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")

    def _notify_error(self, text: str) -> None:
        now = self.clock()
        if now - self._last_error_notify >= ERROR_NOTIFY_INTERVAL:
            self._last_error_notify = now
            self.notifier.send(text)
