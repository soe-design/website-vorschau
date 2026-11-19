"""Konsolen-Kanal zum lokalen Testen – ganz ohne Messenger.

Buttons werden als nummerierte Optionen angezeigt; '#3' drückt Button 3.
"""
from __future__ import annotations

import asyncio
import sys

from .base import Buttons


class ConsoleChannel:
    def __init__(self, tick_seconds: float = 20):
        self.tick_seconds = tick_seconds
        self._buttons: list[str] = []
        self.sent: list[tuple[str, Buttons | None]] = []

    async def send(self, text: str, buttons: Buttons | None = None) -> None:
        self.sent.append((text, buttons))
        print(f"\n🤖 Coach: {text}")
        self._buttons = []
        if buttons:
            opts = []
            for row in buttons:
                for label, data in row:
                    self._buttons.append(data)
                    opts.append(f"#{len(self._buttons)} {label}")
            print("   [" + "  ".join(opts) + "]")
        sys.stdout.flush()

    async def run(self, on_text, on_button, tick) -> None:
        async def ticker():
            while True:
                try:
                    await tick()
                except Exception as e:  # Scheduler darf nie sterben
                    print(f"[tick-Fehler] {e}")
                await asyncio.sleep(self.tick_seconds)

        asyncio.create_task(ticker())
        loop = asyncio.get_running_loop()
        print("Konsole bereit. Schreib etwas (oder /hilfe). Strg+D beendet.")
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if line.startswith("#") and line[1:].isdigit():
                i = int(line[1:]) - 1
                if 0 <= i < len(self._buttons):
                    await on_button(self._buttons[i])
                    continue
            await on_text(line)
