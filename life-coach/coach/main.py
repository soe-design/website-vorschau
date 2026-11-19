"""Einstiegspunkt: python -m coach.main"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .coach import Coach
from .config import load_config
from .db import DB
from .llm import LLM


def build(cfg, channel=None):
    db = DB(cfg.db_path)
    llm = LLM(cfg, db)
    if channel is None:
        if cfg.channel == "telegram":
            from .channels.telegram import TelegramChannel
            channel = TelegramChannel(cfg.telegram_token, cfg.telegram_chat_id)
        else:
            from .channels.console import ConsoleChannel
            channel = ConsoleChannel()
    return Coach(cfg, db, llm, channel)


def _safe(fn):
    async def wrapper(*a):
        try:
            await fn(*a)
        except Exception:
            logging.exception("Fehler bei der Verarbeitung")
    return wrapper


async def amain(args) -> None:
    cfg = load_config(args.env)
    if args.channel:
        cfg.channel = args.channel
    if args.fake:
        cfg.llm_backend = "fake"
    coach = build(cfg)
    logging.info("Coach startet: Kanal=%s, LLM=%s, DB=%s", cfg.channel, cfg.llm_backend, cfg.db_path)
    await coach.ch.run(_safe(coach.handle_text), _safe(coach.handle_callback), coach.tick)


def main() -> None:
    p = argparse.ArgumentParser(description="Persönlicher KI-Life-Coach")
    p.add_argument("--env", help="Pfad zur .env (Standard: ./.env)")
    p.add_argument("--channel", choices=["console", "telegram"])
    p.add_argument("--fake", action="store_true", help="ohne Claude testen (Fake-Antworten)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
