"""Streaks, Trends und Zusammenfassungen – rein lokal, ohne KI."""
from __future__ import annotations

from datetime import date, timedelta

from .db import DB


def one_thing_streak(db: DB, today: date) -> int:
    """Streak für 'das EINE erledigt'. Regel: einmal aussetzen ist ok,
    erst zwei verpasste Tage hintereinander beenden den Streak."""
    rows = {r["date"]: r["one_thing_done"] for r in db.q(
        "SELECT date, one_thing_done FROM days WHERE date <= ?", (today.isoformat(),))}
    streak, misses = 0, 0
    d = today
    # heute zählt nur, wenn schon erledigt (sonst ist der Tag ja noch offen)
    if not rows.get(d.isoformat()):
        d -= timedelta(days=1)
    for _ in range(400):
        if rows.get(d.isoformat()):
            streak += 1
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                break
        d -= timedelta(days=1)
    return streak


def weight_trend(db: DB, today: date) -> dict:
    def avg(start: date, end: date):
        r = db.one("SELECT AVG(kg) a, COUNT(*) n FROM weights WHERE date>? AND date<=?",
                   (start.isoformat(), end.isoformat()))
        return (round(r["a"], 1) if r["a"] else None), r["n"]

    cur, n = avg(today - timedelta(days=7), today)
    prev, _ = avg(today - timedelta(days=14), today - timedelta(days=7))
    last = db.one("SELECT date, kg FROM weights ORDER BY date DESC LIMIT 1")
    return {
        "avg7": cur, "n7": n, "prev_avg7": prev,
        "delta": round(cur - prev, 1) if cur and prev else None,
        "last": (last["kg"], last["date"]) if last else None,
    }


def mood_avg(db: DB, today: date, days: int = 7) -> float | None:
    r = db.one("SELECT AVG(mood) a FROM days WHERE mood IS NOT NULL AND date>? AND date<=?",
               ((today - timedelta(days=days)).isoformat(), today.isoformat()))
    return round(r["a"], 1) if r["a"] is not None else None


def low_mood_days(db: DB, today: date, threshold: int = 3, days: int = 7) -> int:
    r = db.one("SELECT COUNT(*) n FROM days WHERE mood IS NOT NULL AND mood<=? "
               "AND date>? AND date<=?",
               (threshold, (today - timedelta(days=days)).isoformat(), today.isoformat()))
    return r["n"]


def workouts_week(db: DB, today: date) -> dict:
    rows = db.q("SELECT type, COUNT(*) n, COALESCE(SUM(distance_km),0) km, "
                "COALESCE(MAX(handstand_sec),0) hs FROM workouts WHERE date>? AND date<=? "
                "GROUP BY type", ((today - timedelta(days=7)).isoformat(), today.isoformat()))
    return {r["type"]: {"n": r["n"], "km": r["km"], "hs": r["hs"]} for r in rows}


def handstand_best(db: DB) -> float:
    r = db.one("SELECT MAX(handstand_sec) m FROM workouts")
    return r["m"] or 0


def stale_projects(db: DB, today: date, days: int = 5) -> list:
    cutoff = (today - timedelta(days=days)).isoformat()
    return db.q("SELECT * FROM projects WHERE status='aktiv' AND "
                "COALESCE(updated, created) < ? ORDER BY updated", (cutoff,))


def week_summary(db: DB, today: date) -> str:
    start = today - timedelta(days=7)
    days = db.q("SELECT * FROM days WHERE date>? AND date<=? ORDER BY date",
                (start.isoformat(), today.isoformat()))
    done = sum(1 for d in days if d["one_thing_done"])
    meals = db.one("SELECT COUNT(DISTINCT date) d, AVG(k) kcal, AVG(p) prot FROM "
                   "(SELECT date, SUM(kcal) k, SUM(protein) p FROM meals WHERE date>? "
                   "AND date<=? GROUP BY date)", (start.isoformat(), today.isoformat()))
    w = weight_trend(db, today)
    wo = workouts_week(db, today)
    proj = db.q("SELECT p.name, COUNT(l.id) n FROM projects p LEFT JOIN project_log l "
                "ON l.project_id=p.id AND l.ts>? WHERE p.status='aktiv' GROUP BY p.id",
                (start.isoformat(),))
    lines = [
        f"Das EINE erledigt: {done}/7 Tage, Streak {one_thing_streak(db, today)}",
        f"Stimmung Ø {mood_avg(db, today)}",
        f"Gewicht Ø7 {w['avg7']} kg (Vorwoche {w['prev_avg7']}, Δ {w['delta']})",
        f"Essen geloggt an {meals['d']} Tagen, Ø {meals['kcal'] or 0:.0f} kcal / "
        f"{meals['prot'] or 0:.0f} g Eiweiß",
        "Training: " + (", ".join(f"{k} {v['n']}x" + (f" ({v['km']:.1f} km)" if v['km'] else "")
                                  for k, v in wo.items()) or "nichts geloggt"),
        f"Handstand Bestzeit: {handstand_best(db):.0f} s",
        "Projekte (Updates diese Woche): " + (", ".join(f"{p['name']} {p['n']}" for p in proj) or "-"),
    ]
    good = [d["went_well"] for d in days if d["went_well"]]
    bad = [d["went_badly"] for d in days if d["went_badly"]]
    if good:
        lines.append("Lief gut: " + " | ".join(good[-5:]))
    if bad:
        lines.append("Lief nicht: " + " | ".join(bad[-5:]))
    return "\n".join(lines)
