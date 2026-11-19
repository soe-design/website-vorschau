"""Mahlzeiten-Vorschläge, die mit der Zeit dazulernen.

- Auswahl bekannter Rezepte passiert lokal (kostenlos): passt zu den
  restlichen Makros des Tages, zur Tageszeit und zu deinen Bewertungen.
- ~20 % der Vorschläge sind neue Ideen von Claude (Exploration).
- Bewertungen (👍/😐/👎) und "gegessen" verändern künftige Vorschläge.
"""
from __future__ import annotations

import json
import random
from datetime import datetime

from . import nutrition
from .db import DB

EXPLORE_RATE = 0.2

RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "minutes": {"type": "integer"},
        "slot": {"type": "string", "enum": ["frühstück", "mittag", "abend", "snack", "any"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "grams": {"type": "number"}},
                "required": ["item", "grams"],
            },
        },
        "instructions": {"type": "string"},
        "estimated": {
            "type": "object",
            "properties": {k: {"type": "number"} for k in ("kcal", "protein", "carbs", "fat")},
            "required": ["kcal", "protein", "carbs", "fat"],
        },
        "pitch": {"type": "string"},
    },
    "required": ["name", "minutes", "slot", "ingredients", "instructions", "estimated", "pitch"],
}


def slot_for(now: datetime) -> str:
    h = now.hour + now.minute / 60
    if h < 10.5:
        return "frühstück"
    if h < 15:
        return "mittag"
    if h < 17.5:
        return "snack"
    return "abend"


def eaten_today(db: DB, date: str) -> dict:
    row = db.one(
        "SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(protein),0) protein, "
        "COUNT(*) n FROM meals WHERE date=?", (date,))
    return {"kcal": row["kcal"], "protein": row["protein"], "n": row["n"]}


def remaining(db: DB, cfg, date: str) -> dict:
    e = eaten_today(db, date)
    t = targets(db, cfg)
    return {"kcal": t["kcal"] - e["kcal"], "protein": t["protein"] - e["protein"]}


def targets(db: DB, cfg) -> dict:
    t = db.get("targets") or {}
    return {"kcal": t.get("kcal", cfg.kcal_target),
            "protein": t.get("protein", cfg.protein_target)}


def score(r, rem: dict, slot: str, today: str) -> float:
    s = 2.0 * r["likes"] - 3.0 * r["dislikes"] + 0.5 * min(r["eaten"], 10)
    if r["slot"] not in (slot, "any"):
        s -= 4
    kcal = r["kcal"] or 1
    # Eiweißdichte zählt mehr, je mehr Eiweiß noch fehlt
    density = (r["protein"] or 0) / kcal * 100  # g Protein pro 100 kcal
    need = max(rem["protein"], 0) / 50
    s += density * (0.5 + need)
    if rem["kcal"] > 0 and kcal > rem["kcal"] * 1.15:
        s -= (kcal - rem["kcal"]) / 100
    if r["last_suggested"] and r["last_suggested"][:10] == today:
        s -= 5
    return s + random.uniform(0, 1.5)  # etwas Abwechslung


def pick_known(db: DB, cfg, now: datetime):
    today = now.date().isoformat()
    rem = remaining(db, cfg, today)
    slot = slot_for(now)
    rows = db.q("SELECT * FROM recipes WHERE dislikes < 3 OR likes > dislikes")
    if not rows:
        return None, rem, slot
    best = max(rows, key=lambda r: score(r, rem, slot, today))
    return best, rem, slot


def mark_suggested(db: DB, recipe_id: int, now: datetime) -> int:
    db.x("UPDATE recipes SET last_suggested=? WHERE id=?",
         (now.isoformat(timespec="seconds"), recipe_id))
    return db.x("INSERT INTO meal_suggestions(ts,recipe_id) VALUES(?,?)",
                (now.isoformat(timespec="seconds"), recipe_id))


def rate(db: DB, recipe_id: int, rating: str, now: datetime, cfg=None) -> str:
    """rating: like | ok | dislike | eaten"""
    r = db.one("SELECT * FROM recipes WHERE id=?", (recipe_id,))
    if not r:
        return "Rezept nicht gefunden."
    if rating == "like":
        db.x("UPDATE recipes SET likes=likes+1 WHERE id=?", (recipe_id,))
        msg = f"👍 Gemerkt: {r['name']} kommt öfter."
    elif rating == "dislike":
        db.x("UPDATE recipes SET dislikes=dislikes+1 WHERE id=?", (recipe_id,))
        msg = f"👎 Ok, {r['name']} schlage ich seltener vor."
    elif rating == "eaten":
        db.x("UPDATE recipes SET eaten=eaten+1, likes=likes+1 WHERE id=?", (recipe_id,))
        db.x("INSERT INTO meals(ts,date,name,kcal,protein,recipe_id) VALUES(?,?,?,?,?,?)",
             (now.isoformat(timespec="seconds"), now.date().isoformat(), r["name"],
              r["kcal"], r["protein"], recipe_id))
        msg = f"✅ Eingetragen: {r['name']} ({r['kcal']:.0f} kcal, {r['protein']:.0f} g Eiweiß)."
        if cfg is not None:
            rem = remaining(db, cfg, now.date().isoformat())
            msg += f"\nHeute noch: {rem['kcal']:.0f} kcal, {rem['protein']:.0f} g Eiweiß."
    else:
        msg = "😐 Notiert."
    db.x("UPDATE meal_suggestions SET rating=? WHERE id=(SELECT MAX(id) FROM "
         "meal_suggestions WHERE recipe_id=?)", (rating, recipe_id))
    return msg


def format_recipe(r, rem: dict | None = None, pitch: str = "") -> str:
    ing = json.loads(r["ingredients"] or "[]")
    lines = [f"🍽 *{r['name']}* · {r['minutes']} min"]
    if pitch:
        lines.append(pitch)
    lines.append(
        f"{r['kcal']:.0f} kcal · {r['protein']:.0f} g Eiweiß · "
        f"{r['carbs']:.0f} g KH · {r['fat']:.0f} g Fett"
        + ("" if r["macros_verified"] else " (geschätzt)")
    )
    lines += [f"• {i['grams']:.0f} g {i['item']}" for i in ing]
    if r["instructions"]:
        lines.append(r["instructions"])
    if rem:
        lines.append(f"_Heute noch offen: {rem['kcal']:.0f} kcal, {rem['protein']:.0f} g Eiweiß_")
    return "\n".join(lines)


def rating_buttons(recipe_id: int) -> list[list[tuple[str, str]]]:
    return [[("✅ gegessen", f"meal:eaten:{recipe_id}"), ("👍", f"meal:like:{recipe_id}"),
             ("👎", f"meal:dislike:{recipe_id}"), ("🔄 anderes", "meal:next:0")]]


def recipe_prompt(db: DB, rem: dict, slot: str, wish: str, profile_text: str) -> str:
    liked = [r["name"] for r in db.q(
        "SELECT name FROM recipes WHERE likes > dislikes ORDER BY likes DESC LIMIT 8")]
    disliked = [r["name"] for r in db.q(
        "SELECT name FROM recipes WHERE dislikes >= 2 ORDER BY dislikes DESC LIMIT 8")]
    known_foods = ", ".join(sorted(nutrition.foods(db)))
    return (
        f"Erfinde EINE neue Mahlzeit ({slot}).\n"
        f"Noch offen heute: {rem['kcal']:.0f} kcal, {rem['protein']:.0f} g Eiweiß.\n"
        f"Wunsch/Situation: {wish or '-'}\n"
        f"Über mich:\n{profile_text}\n"
        f"Mag ich: {', '.join(liked) or '-'}\nMag ich nicht: {', '.join(disliked) or '-'}\n"
        "Zutaten aus österreichischen Supermärkten (Billa/Spar/Hofer/Lidl), wenig Aufwand, "
        "eiweißreich, passend für eine Diät (leichtes Defizit). "
        "Benutze für Zutaten möglichst exakt diese Namen, damit die Makros berechnet "
        f"werden können: {known_foods}.\n"
        "Gib realistische Grammangaben und eine Makro-Schätzung. 'pitch' = 1 kurzer Satz, "
        "warum das gerade passt."
    )
