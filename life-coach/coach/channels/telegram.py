"""Telegram-Kanal (python-telegram-bot, Long-Polling – kein offener Port nötig)."""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from .base import Buttons

log = logging.getLogger(__name__)


class TelegramChannel:
    def __init__(self, token: str, chat_id: str, tick_seconds: float = 20):
        if not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN fehlt in .env")
        self.token = token
        self.chat_id = chat_id
        self.tick_seconds = tick_seconds
        self.app: Application | None = None

    def _allowed(self, update: Update) -> bool:
        cid = str(update.effective_chat.id) if update.effective_chat else ""
        if not self.chat_id:
            # Erste Einrichtung: Chat-ID anzeigen, aber sonst nichts tun
            log.warning("Nachricht von Chat-ID %s – trage sie als TELEGRAM_CHAT_ID in .env ein.", cid)
            return False
        return cid == str(self.chat_id)

    async def send(self, text: str, buttons: Buttons | None = None) -> None:
        if not self.app or not self.chat_id:
            log.info("(nicht gesendet, keine Chat-ID) %s", text)
            return
        markup = None
        if buttons:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(l, callback_data=d) for l, d in row] for row in buttons])
        for chunk in _chunks(text, 4000):
            try:
                await self.app.bot.send_message(self.chat_id, chunk, parse_mode=ParseMode.MARKDOWN,
                                                reply_markup=markup)
            except BadRequest:  # kaputtes Markdown -> als Klartext senden
                await self.app.bot.send_message(self.chat_id, chunk, reply_markup=markup)
            markup = None

    async def run(self, on_text, on_button, tick) -> None:
        self.app = Application.builder().token(self.token).build()

        async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if update.message and update.message.text is not None:
                if not self.chat_id:
                    await update.message.reply_text(
                        f"Deine Chat-ID ist {update.effective_chat.id}. Trag sie als "
                        "TELEGRAM_CHAT_ID in die .env ein und starte den Coach neu.")
                    return
                if self._allowed(update):
                    await on_text(update.message.text)

        async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            q = update.callback_query
            await q.answer()
            if self._allowed(update):
                try:
                    await q.edit_message_reply_markup(None)  # Buttons nach Klick entfernen
                except BadRequest:
                    pass
                await on_button(q.data)

        self.app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, text_handler))
        self.app.add_handler(CallbackQueryHandler(button_handler))

        async with self.app:
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=False)
            log.info("Telegram-Bot läuft.")
            try:
                while True:
                    try:
                        await tick()
                    except Exception:
                        log.exception("Fehler im Scheduler")
                    await asyncio.sleep(self.tick_seconds)
            finally:
                await self.app.updater.stop()
                await self.app.stop()


def _chunks(text: str, n: int):
    for i in range(0, len(text), n):
        yield text[i:i + n]
