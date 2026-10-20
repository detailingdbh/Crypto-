"""Start the trading bot: python run.py [--config config.yaml] [--once]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from bot.broker import LiveBroker, MarketData, PaperBroker, make_exchange
from bot.config import ConfigError, load_config
from bot.notify import Notifier
from bot.runner import Bot
from bot.state import StateStore


def setup_logging(data_dir: str) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(Path(data_dir) / "bot.log", maxBytes=5_000_000, backupCount=3)
    console = logging.StreamHandler(sys.stdout)
    for h in (file_handler, console):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console])


def main() -> int:
    parser = argparse.ArgumentParser(description="Bot de trading crypto")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="une seule analyse puis arrêt")
    args = parser.parse_args()

    load_dotenv()
    try:
        cfg = load_config(args.config)
    except (ConfigError, TypeError) as e:
        print(f"Configuration invalide : {e}", file=sys.stderr)
        return 2
    setup_logging(cfg.data_dir)
    log = logging.getLogger("run")

    store = StateStore(Path(cfg.data_dir) / "state.json")
    state = store.load()

    if cfg.mode == "live":
        if os.getenv("LIVE_TRADING_CONFIRMED", "").lower() != "oui":
            log.error("mode live refusé : mets LIVE_TRADING_CONFIRMED=oui dans .env si tu acceptes de risquer ton argent")
            return 2
        exchange = make_exchange(
            cfg.exchange,
            api_key=os.getenv("EXCHANGE_API_KEY", ""),
            secret=os.getenv("EXCHANGE_SECRET", ""),
            private_key=os.getenv("EXCHANGE_PRIVATE_KEY", ""),
        )
        broker = LiveBroker(exchange)
        log.warning("MODE LIVE : le bot passe de VRAIS ordres sur %s", cfg.exchange)
    else:
        if not state.paper_balances:
            state.paper_balances = {cfg.quote: cfg.paper.starting_balance}
        broker = PaperBroker(MarketData(make_exchange(cfg.exchange)), state.paper_balances, cfg.paper.fee_rate)
        log.info("mode simulation : solde fictif %s", state.paper_balances)

    notifier = Notifier(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""))
    bot = Bot(cfg, broker, store, state, notifier)
    if args.once:
        bot.tick()
    else:
        bot.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
