"""Load and validate the bot configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(ValueError):
    pass


@dataclass
class StrategyConfig:
    ema_fast: int = 12
    ema_slow: int = 26
    trend_ema: int = 200
    rsi_period: int = 14
    rsi_max_buy: float = 70
    atr_period: int = 14


@dataclass
class RiskConfig:
    quote_per_trade: float = 20
    max_open_positions: int = 3
    stop_loss_atr: float = 2.0
    take_profit_atr: float = 4.0
    max_daily_loss: float = 50
    max_trades_per_day: int = 10


@dataclass
class PaperConfig:
    starting_balance: float = 1000
    fee_rate: float = 0.001


@dataclass
class Config:
    exchange: str = "revolutx"
    mode: str = "paper"
    symbols: list[str] = field(default_factory=lambda: ["BTC/EUR"])
    timeframe: str = "1h"
    candles: int = 300
    poll_seconds: int = 60
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    data_dir: str = "data"

    @property
    def quote(self) -> str:
        return self.symbols[0].split("/")[1]

    def validate(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ConfigError("mode doit être 'paper' ou 'live'")
        if not self.symbols:
            raise ConfigError("symbols ne peut pas être vide")
        for s in self.symbols:
            if s.count("/") != 1:
                raise ConfigError(f"symbole invalide : {s} (format attendu BASE/QUOTE)")
        quotes = {s.split("/")[1] for s in self.symbols}
        if len(quotes) != 1:
            raise ConfigError(f"toutes les paires doivent avoir la même devise de cotation, trouvé {quotes}")
        st = self.strategy
        if not 0 < st.ema_fast < st.ema_slow:
            raise ConfigError("il faut 0 < ema_fast < ema_slow")
        needed = max(st.ema_slow, st.trend_ema, st.rsi_period, st.atr_period) + 2
        if self.candles < needed:
            raise ConfigError(f"candles doit valoir au moins {needed}")
        r = self.risk
        if r.quote_per_trade <= 0 or r.max_open_positions < 1:
            raise ConfigError("quote_per_trade et max_open_positions doivent être positifs")
        if r.stop_loss_atr <= 0 or r.take_profit_atr <= 0:
            raise ConfigError("stop_loss_atr et take_profit_atr doivent être positifs")
        if self.poll_seconds < 5:
            raise ConfigError("poll_seconds doit valoir au moins 5 (limites de l'exchange)")


def load_config(path: str | os.PathLike) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"{p} introuvable : copie config.example.yaml en config.yaml")
    raw = yaml.safe_load(p.read_text()) or {}
    cfg = Config(
        strategy=StrategyConfig(**(raw.pop("strategy", None) or {})),
        risk=RiskConfig(**(raw.pop("risk", None) or {})),
        paper=PaperConfig(**(raw.pop("paper", None) or {})),
        **raw,
    )
    cfg.validate()
    return cfg
