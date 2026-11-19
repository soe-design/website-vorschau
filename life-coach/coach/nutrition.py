"""Nährwert-Tabelle (pro 100 g) und Start-Rezepte.

Die Werte sind gerundete Durchschnittswerte typischer Produkte aus
österreichischen Supermärkten. Für eigene Produkte einfach über
`/zutat name kcal protein kh fett` ergänzen – die Tabelle lernt mit.
"""
from __future__ import annotations

import json
from datetime import datetime

from .db import DB

# name: (kcal, protein, kohlenhydrate, fett) pro 100 g
BASE_FOODS: dict[str, tuple[float, float, float, float]] = {
    "magertopfen": (67, 12, 4, 0.3),
    "skyr": (63, 11, 4, 0.2),
    "griechisches joghurt 2%": (75, 9, 4, 2),
    "hüttenkäse": (98, 12, 3, 4.3),
    "ei": (143, 12.6, 0.7, 9.9),
    "eiklar": (48, 11, 0.7, 0.2),
    "hühnerbrust": (110, 23, 0, 1.5),
    "putenbrust": (105, 24, 0, 1),
    "faschiertes rind mager": (170, 20, 0, 10),
    "lachs": (200, 20, 0, 13),
    "thunfisch natur dose": (110, 25, 0, 1),
    "garnelen": (80, 18, 0.5, 1),
    "tofu natur": (125, 13, 2, 7),
    "linsen gekocht": (116, 9, 20, 0.4),
    "kichererbsen dose": (120, 7, 16, 2.5),
    "kidneybohnen dose": (95, 7, 13, 0.5),
    "reis roh": (350, 7, 78, 0.6),
    "nudeln roh": (355, 12, 71, 1.5),
    "haferflocken": (370, 13, 59, 7),
    "kartoffeln": (77, 2, 17, 0.1),
    "vollkornbrot": (220, 8, 40, 2),
    "wrap vollkorn": (300, 9, 50, 6),
    "brokkoli": (35, 3, 4, 0.4),
    "tk-gemüsemischung": (45, 2.5, 6, 0.5),
    "paprika": (30, 1, 6, 0.3),
    "tomaten": (18, 0.9, 3, 0.2),
    "gurke": (12, 0.6, 2, 0.1),
    "salat": (15, 1.3, 2, 0.2),
    "spinat tk": (25, 3, 1, 0.4),
    "zwiebel": (40, 1.1, 9, 0.1),
    "beeren tk": (45, 1, 8, 0.3),
    "banane": (93, 1.1, 21, 0.3),
    "apfel": (54, 0.3, 12, 0.2),
    "olivenöl": (884, 0, 0, 100),
    "feta light": (180, 17, 1, 12),
    "mozzarella light": (165, 19, 1, 9),
    "parmesan": (390, 33, 0, 28),
    "proteinpulver": (380, 75, 8, 6),
    "milch 1.5%": (47, 3.4, 4.8, 1.5),
    "erdnussmus": (600, 25, 13, 50),
    "tomatensauce passiert": (35, 1.5, 6, 0.3),
    "kakao ungesüßt": (350, 20, 11, 21),
}

# Start-Rezepte: eiweißreich, schnell, wiederholbar
SEED_RECIPES = [
    ("Topfen-Beeren-Bowl", "frühstück", 5, ["süß", "schnell", "kein kochen"],
     [("magertopfen", 250), ("beeren tk", 120), ("haferflocken", 40)],
     "Topfen mit etwas Wasser glatt rühren, Beeren und Haferflocken drauf."),
    ("Rührei mit Spinat & Brot", "frühstück", 10, ["herzhaft", "warm"],
     [("ei", 150), ("eiklar", 100), ("spinat tk", 100), ("vollkornbrot", 60)],
     "Spinat in der Pfanne auftauen, Eier + Eiklar dazu, stocken lassen."),
    ("Overnight Oats Protein", "frühstück", 5, ["süß", "meal-prep"],
     [("haferflocken", 60), ("milch 1.5%", 200), ("proteinpulver", 30), ("banane", 100)],
     "Am Vorabend alles in ein Glas, über Nacht in den Kühlschrank."),
    ("Hühner-Reis-Brokkoli", "mittag", 25, ["herzhaft", "meal-prep", "klassiker"],
     [("hühnerbrust", 200), ("reis roh", 70), ("brokkoli", 200), ("olivenöl", 5)],
     "Reis kochen, Huhn würzen und anbraten, Brokkoli dämpfen."),
    ("Thunfisch-Kichererbsen-Salat", "mittag", 10, ["kalt", "schnell", "kein kochen"],
     [("thunfisch natur dose", 130), ("kichererbsen dose", 150), ("gurke", 100),
      ("tomaten", 100), ("feta light", 30), ("olivenöl", 5)],
     "Alles klein schneiden und mischen, mit Zitrone/Salz/Pfeffer würzen."),
    ("Puten-Wrap", "mittag", 10, ["schnell", "unterwegs"],
     [("wrap vollkorn", 65), ("putenbrust", 150), ("salat", 40), ("paprika", 80),
      ("griechisches joghurt 2%", 50)],
     "Pute anbraten, mit Gemüse und Joghurt-Sauce in den Wrap."),
    ("Chili con Carne (mager)", "abend", 30, ["herzhaft", "meal-prep", "scharf"],
     [("faschiertes rind mager", 150), ("kidneybohnen dose", 120),
      ("tomatensauce passiert", 200), ("zwiebel", 50), ("paprika", 80)],
     "Zwiebel + Faschiertes anbraten, Rest dazu, 20 min köcheln. Gut für 3 Portionen."),
    ("Lachs mit Kartoffeln & Gemüse", "abend", 25, ["herzhaft", "ofen"],
     [("lachs", 150), ("kartoffeln", 250), ("tk-gemüsemischung", 200)],
     "Alles aufs Blech, 20 min bei 200 °C."),
    ("Linsen-Bolognese", "abend", 25, ["vegetarisch", "meal-prep"],
     [("linsen gekocht", 200), ("nudeln roh", 70), ("tomatensauce passiert", 200),
      ("parmesan", 10)],
     "Linsen in Tomatensauce köcheln, über die Nudeln."),
    ("Protein-Shake + Apfel", "snack", 2, ["süß", "schnell", "unterwegs"],
     [("proteinpulver", 30), ("milch 1.5%", 250), ("apfel", 150)],
     "Shaken, Apfel dazu."),
    ("Skyr mit Kakao", "snack", 2, ["süß", "schnell", "abends"],
     [("skyr", 250), ("kakao ungesüßt", 8)],
     "Kakao unterrühren, nach Wunsch Süßstoff."),
    ("Hüttenkäse-Brot", "snack", 3, ["herzhaft", "schnell"],
     [("vollkornbrot", 60), ("hüttenkäse", 150), ("tomaten", 80)],
     "Brot mit Hüttenkäse und Tomaten belegen."),
]


def foods(db: DB) -> dict[str, tuple[float, float, float, float]]:
    table = dict(BASE_FOODS)
    table.update({k: tuple(v) for k, v in (db.get("custom_foods", {}) or {}).items()})
    return table


def norm(name: str) -> str:
    return name.strip().lower()


def macros_for(db: DB, ingredients: list[dict]) -> tuple[dict, bool]:
    """Summiert Makros aus der Tabelle. Rückgabe: (makros, alle_bekannt)."""
    table = foods(db)
    total = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    all_known = True
    for ing in ingredients:
        vals = table.get(norm(ing["item"]))
        if not vals:
            all_known = False
            continue
        f = float(ing["grams"]) / 100
        for k, v in zip(total, vals):
            total[k] += v * f
    return {k: round(v, 1) for k, v in total.items()}, all_known


def add_recipe(db: DB, name, slot, minutes, tags, ingredients, instructions,
               source="seed", estimated: dict | None = None) -> int:
    ing = [
        {"item": norm(i[0]), "grams": float(i[1])} if isinstance(i, (tuple, list))
        else {"item": norm(i["item"]), "grams": float(i["grams"])}
        for i in ingredients
    ]
    m, known = macros_for(db, ing)
    if not known and estimated:
        # unbekannte Zutaten -> KI-Schätzung verwenden, als unverifiziert markieren
        m = {k: float(estimated.get(k, m[k])) for k in m}
    now = datetime.now().isoformat(timespec="seconds")
    db.x(
        "INSERT OR IGNORE INTO recipes(name,kcal,protein,carbs,fat,minutes,slot,"
        "tags,ingredients,instructions,source,macros_verified,created) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, m["kcal"], m["protein"], m["carbs"], m["fat"], minutes, slot,
         json.dumps(tags, ensure_ascii=False), json.dumps(ing, ensure_ascii=False),
         instructions, source, int(known), now),
    )
    row = db.one("SELECT id FROM recipes WHERE name=?", (name,))
    return row["id"]


def seed(db: DB) -> None:
    if db.get("seeded"):
        return
    for name, slot, minutes, tags, ing, instr in SEED_RECIPES:
        add_recipe(db, name, slot, minutes, tags, ing, instr)
    db.set("seeded", True)
