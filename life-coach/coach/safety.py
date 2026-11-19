"""Krisenerkennung – bewusst deterministisch, unabhängig von der KI."""
from __future__ import annotations

import re

CRISIS_PATTERNS = [
    r"\bumbringen\b", r"\bsuizid", r"\bselbstmord", r"\bmich (töten|umbringen)",
    r"nicht mehr leben", r"will nicht mehr (leben|da sein|aufwachen)",
    r"\bsterben will", r"\bwill sterben", r"\bmir (was|etwas) antun",
    r"\bselbstverletz", r"\britzen\b", r"alles beenden",
]
_RX = re.compile("|".join(CRISIS_PATTERNS), re.I)

CRISIS_MESSAGE = (
    "Ich nehme das ernst, was du gerade schreibst. 💛\n\n"
    "Bitte sprich jetzt mit einem Menschen – du musst das nicht allein tragen:\n"
    "• *Telefonseelsorge 142* – rund um die Uhr, kostenlos, anonym (auch Chat: telefonseelsorge.at)\n"
    "• *Notruf 144* bei akuter Gefahr\n"
    "• *Rat auf Draht 147* (für junge Menschen)\n"
    "• Oder ruf jetzt eine Person an, der du vertraust.\n\n"
    "Ich bin ein Programm und kein Ersatz für echte Hilfe – aber ich bin weiter da, "
    "wenn du schreiben willst."
)

LOW_MOOD_NOTE = (
    "Hinweis für den Coach: In den letzten Tagen war die Stimmung mehrfach sehr niedrig. "
    "Sprich das behutsam und ehrlich an, ohne zu drängen. Ermutige, mit Freund:innen/"
    "Familie oder professioneller Hilfe zu reden (Telefonseelsorge 142, Hausärzt:in). "
    "Heute keine Leistungs-Challenges, nur sehr kleine, freundliche Schritte."
)


def is_crisis(text: str) -> bool:
    return bool(_RX.search(text or ""))
