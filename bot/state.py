"""Persistent bot state (open positions, daily counters, trade history)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_HISTORY = 500


@dataclass
class Position:
    symbol: str
    amount: float
    entry_price: float
    cost: float  # quote spent, fees included
    stop: float
    take_profit: float
    opened_at: str


@dataclass
class State:
    positions: dict[str, Position] = field(default_factory=dict)
    day: str = ""
    daily_pnl: float = 0.0
    trades_today: int = 0
    total_pnl: float = 0.0
    last_entry_candle: dict[str, int] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    paper_balances: dict[str, float] = field(default_factory=dict)

    def roll_day(self, day: str) -> None:
        if day != self.day:
            self.day = day
            self.daily_pnl = 0.0
            self.trades_today = 0

    def record(self, entry: dict) -> None:
        self.history.append(entry)
        del self.history[:-MAX_HISTORY]


class StateStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def load(self) -> State:
        if not self.path.exists():
            return State()
        raw = json.loads(self.path.read_text())
        positions = {k: Position(**v) for k, v in raw.pop("positions", {}).items()}
        return State(positions=positions, **raw)

    def save(self, state: State) -> None:
        """Write atomically so a crash never leaves a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(state)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
