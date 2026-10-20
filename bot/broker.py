"""Order execution: a live broker on top of ccxt, and a paper broker that simulates fills."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

import ccxt

log = logging.getLogger(__name__)
T = TypeVar("T")


class OrderRejected(Exception):
    """The order cannot be placed (too small, insufficient balance...)."""


@dataclass
class Fill:
    amount: float  # base received (buy) or sold (sell), net of base-currency fees
    price: float
    quote: float  # quote spent (buy, fees included) or received (sell, fees deducted)


class Broker(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]: ...
    def fetch_price(self, symbol: str) -> float: ...
    def quote_balance(self, quote: str) -> float: ...
    def buy(self, symbol: str, quote_amount: float, price: float) -> Fill: ...
    def sell(self, symbol: str, amount: float, price: float) -> Fill: ...


def with_retry(fn: Callable[[], T], attempts: int = 4, base_delay: float = 2.0, sleep=time.sleep) -> T:
    """Retry transient network errors with exponential backoff (2s, 4s, 8s)."""
    for i in range(attempts):
        try:
            return fn()
        except (ccxt.NetworkError, ccxt.RateLimitExceeded) as e:
            if i == attempts - 1:
                raise
            delay = base_delay * 2**i
            log.warning("erreur réseau (%s), nouvel essai dans %.0fs", e.__class__.__name__, delay)
            sleep(delay)
    raise AssertionError("unreachable")


def make_exchange(name: str, api_key: str = "", secret: str = "", private_key: str = "") -> ccxt.Exchange:
    if name not in ccxt.exchanges:
        raise ValueError(f"exchange inconnu de ccxt : {name}")
    params: dict = {"enableRateLimit": True}
    if api_key:
        params["apiKey"] = api_key
    if secret:
        params["secret"] = secret
    if private_key:
        params["privateKey"] = private_key
    return getattr(ccxt, name)(params)


class MarketData:
    """Public market data shared by both brokers."""

    def __init__(self, exchange: ccxt.Exchange):
        self.ex = exchange
        with_retry(self.ex.load_markets)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        return with_retry(lambda: self.ex.fetch_ohlcv(symbol, timeframe, limit=limit))

    def fetch_price(self, symbol: str) -> float:
        t = with_retry(lambda: self.ex.fetch_ticker(symbol))
        price = t.get("last") or t.get("close") or t.get("bid")
        if not price:
            raise ccxt.ExchangeError(f"pas de prix pour {symbol}")
        return float(price)

    def check_order_size(self, symbol: str, amount: float, price: float) -> float:
        """Round amount to the market precision and enforce minimums."""
        amount = float(self.ex.amount_to_precision(symbol, amount))
        limits = self.ex.market(symbol).get("limits", {})
        min_amount = (limits.get("amount") or {}).get("min")
        min_cost = (limits.get("cost") or {}).get("min")
        if amount <= 0 or (min_amount and amount < min_amount):
            raise OrderRejected(f"quantité trop petite pour {symbol} : {amount}")
        if min_cost and amount * price < min_cost:
            raise OrderRejected(f"montant trop petit pour {symbol} : {amount * price:.2f} < {min_cost}")
        return amount


class LiveBroker(MarketData):
    """Places real market orders. Every call here moves real money."""

    def quote_balance(self, quote: str) -> float:
        bal = with_retry(self.ex.fetch_balance)
        return float((bal.get("free") or {}).get(quote) or 0)

    def buy(self, symbol: str, quote_amount: float, price: float) -> Fill:
        amount = self.check_order_size(symbol, quote_amount / price, price)
        # No retry on order creation: a timeout could hide a filled order and cause a double buy.
        order = self.ex.create_order(symbol, "market", "buy", amount)
        return self._fill(symbol, order, "buy", amount, price)

    def sell(self, symbol: str, amount: float, price: float) -> Fill:
        base = symbol.split("/")[0]
        bal = with_retry(self.ex.fetch_balance)
        free = float((bal.get("free") or {}).get(base) or 0)
        amount = self.check_order_size(symbol, min(amount, free), price)
        order = self.ex.create_order(symbol, "market", "sell", amount)
        return self._fill(symbol, order, "sell", amount, price)

    def _fill(self, symbol: str, order: dict, side: str, requested: float, price: float) -> Fill:
        oid = order.get("id")
        if oid and not order.get("filled"):
            try:
                order = with_retry(lambda: self.ex.fetch_order(oid, symbol))
            except Exception as e:  # the order exists; fall back to requested values
                log.warning("impossible de relire l'ordre %s : %s", oid, e)
        filled = float(order.get("filled") or requested)
        avg = float(order.get("average") or order.get("price") or price)
        cost = float(order.get("cost") or filled * avg)
        base, quote = symbol.split("/")
        fee_base = fee_quote = 0.0
        for fee in order.get("fees") or ([order["fee"]] if order.get("fee") else []):
            if not fee or fee.get("cost") is None:
                continue
            if fee.get("currency") == base:
                fee_base += float(fee["cost"])
            elif fee.get("currency") == quote:
                fee_quote += float(fee["cost"])
        if side == "buy":
            return Fill(amount=filled - fee_base, price=avg, quote=cost + fee_quote)
        return Fill(amount=filled, price=avg, quote=cost - fee_quote)


class PaperBroker:
    """Simulated trading on real market prices. Balances live in the bot state."""

    def __init__(self, market: MarketData | Broker, balances: dict[str, float], fee_rate: float):
        self.market = market
        self.balances = balances
        self.fee_rate = fee_rate

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        return self.market.fetch_ohlcv(symbol, timeframe, limit)

    def fetch_price(self, symbol: str) -> float:
        return self.market.fetch_price(symbol)

    def quote_balance(self, quote: str) -> float:
        return self.balances.get(quote, 0.0)

    def buy(self, symbol: str, quote_amount: float, price: float) -> Fill:
        base, quote = symbol.split("/")
        if quote_amount > self.balances.get(quote, 0.0) + 1e-12:
            raise OrderRejected(f"solde {quote} insuffisant")
        amount = quote_amount * (1 - self.fee_rate) / price
        self.balances[quote] = self.balances.get(quote, 0.0) - quote_amount
        self.balances[base] = self.balances.get(base, 0.0) + amount
        return Fill(amount=amount, price=price, quote=quote_amount)

    def sell(self, symbol: str, amount: float, price: float) -> Fill:
        base, quote = symbol.split("/")
        amount = min(amount, self.balances.get(base, 0.0))
        if amount <= 0:
            raise OrderRejected(f"aucun {base} à vendre")
        proceeds = amount * price * (1 - self.fee_rate)
        self.balances[base] -= amount
        self.balances[quote] = self.balances.get(quote, 0.0) + proceeds
        return Fill(amount=amount, price=price, quote=proceeds)
