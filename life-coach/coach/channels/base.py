"""Austauschbare Kanal-Schnittstelle (Telegram, Konsole, später SMS/WhatsApp)."""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol

# Buttons: Zeilen von (Beschriftung, callback_data)
Buttons = list[list[tuple[str, str]]]
TextHandler = Callable[[str], Awaitable[None]]


class Channel(Protocol):
    async def send(self, text: str, buttons: Buttons | None = None) -> None: ...

    async def run(self, on_text: TextHandler, on_button: TextHandler,
                  tick: Callable[[], Awaitable[None]]) -> None:
        """Startet den Empfang und ruft `tick` regelmäßig (Scheduler) auf."""
        ...
