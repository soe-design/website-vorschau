"""Kernlogik des Coaches: Nachrichten verarbeiten, Check-ins, Nachhaken, Wochenrückblick."""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta

from . import meals, nutrition, prompts, safety, stats
from .channels.base import Buttons, Channel
from .db import DB
from .llm import LLM

log = logging.getLogger(__name__)

DAY_FIELDS = {"wake_time", "sleep_time", "mood", "energy", "one_thing", "one_thing_min",
              "went_well", "went_badly", "tomorrow"}

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Vorlagen, wenn die KI nicht verfügbar ist (Guthaben leer, Fehler, offline)
FALLBACK = {
    "morgen": ["Guten Morgen! ☀️ Was ist heute das EINE Wichtige – und was ist die 2-Minuten-Version davon?",
               "Aufstehen, Fenster auf, Glas Wasser. 💧 Und dann: Was ist heute dein EINES Ding?"],
    "vormittag": ["Kurzer Check: Erster Schritt fürs EINE schon gemacht? Wenn nicht – nur 2 Minuten, jetzt."],
    "mittag": ["Mittag! 🍽 Genug Eiweiß dabei? Wie ist die Energie (1–10)?"],
    "bewegung": ["Zeit für Bewegung 🏃 – Laufen, Handstand an der Wand oder 10 Minuten irgendwas. Was wird's?"],
    "abend": ["Tagesbilanz 🌙 Was lief heute gut, was nicht – und was ist morgen das EINE? Danach Handy weg."],
}
FOLLOWUPS = [
    "Kurz nachgehakt 🙂 – ein Wort reicht auch.",
    "Noch da? Eine Zahl von 1–10 für deinen Tag reicht mir schon.",
    "Kein Stress – aber ich bin neugierig: wie läuft's?",
]
MOOD_BUTTONS: Buttons = [
    [(str(i), f"mood:{i}") for i in range(1, 6)],
    [(str(i), f"mood:{i}") for i in range(6, 11)],
]

HELP = """*Befehle*
/status – heute, Streak, Kalorien
/essen [wunsch] – Mahlzeit-Vorschlag (z. B. /essen schnell, herzhaft)
/gewicht 82.4 – Gewicht eintragen
/projekte – Projektliste
/neu Name | Ziel | nächster Schritt | Deadline – Projekt anlegen
/ziel kcal 2100 protein 160 – Ernährungsziele
/zutat name kcal protein kh fett – eigene Zutat (pro 100 g)
/merken Text – etwas, das ich mir merken soll
/ruhe [stunden] – Pause (Standard 4 h), /ruhe aus
/woche – Wochenrückblick jetzt
/kosten – KI-Verbrauch diesen Monat
Sonst einfach normal schreiben – ich verstehe Freitext."""


class Coach:
    def __init__(self, cfg, db: DB, llm: LLM, channel: Channel):
        self.cfg, self.db, self.llm, self.ch = cfg, db, llm, channel
        nutrition.seed(db)

    # ------------------------------------------------------------- helpers
    def now(self) -> datetime:
        return datetime.now(self.cfg.tz)

    def today(self) -> str:
        return self.now().date().isoformat()

    async def send(self, text: str, buttons: Buttons | None = None, kind: str = "chat"):
        self.db.x("INSERT INTO messages(ts,direction,text,kind) VALUES(?,?,?,?)",
                  (self.now().isoformat(timespec="seconds"), "out", text, kind))
        await self.ch.send(text, buttons)

    def _log_in(self, text: str) -> None:
        now = self.now()
        self.db.x("INSERT INTO messages(ts,direction,text,kind) VALUES(?,?,?,?)",
                  (now.isoformat(timespec="seconds"), "in", text, "chat"))
        # alle offenen Check-ins von heute gelten als beantwortet
        self.db.x("UPDATE checkins SET answered=1 WHERE date=? AND answered=0", (self.today(),))
        # erste Nachricht vor 11 Uhr = ungefähre Aufstehzeit
        d = self.db.day(self.today())
        if not d["wake_time"] and now.hour < 11:
            self.db.update_day(self.today(), wake_time=now.strftime("%H:%M"))

    # ------------------------------------------------------------- context
    def context(self, checkin: str | None = None) -> str:
        now = self.now()
        today = now.date()
        d = self.db.day(today.isoformat())
        t = meals.targets(self.db, self.cfg)
        eaten = meals.eaten_today(self.db, today.isoformat())
        w = stats.weight_trend(self.db, today)
        parts = [
            f"Jetzt: {WEEKDAYS_DE[now.weekday()]}, {now:%d.%m.%Y %H:%M}"
            + (f" – geplanter Check-in: {checkin}" if checkin else ""),
        ]
        facts = self.db.q("SELECT id, fact FROM facts WHERE active=1 ORDER BY id DESC LIMIT 30")
        if facts:
            parts.append("Über mich:\n" + "\n".join(f"- {f['fact']}" for f in reversed(facts)))
        if (tp := self.db.get("taste_profile")):
            parts.append(f"Essprofil: {tp}")
        if (cn := self.db.get("coach_notes")):
            parts.append(f"Deine Notizen aus dem letzten Wochenrückblick: {cn}")
        today_bits = [
            f"das EINE: {d['one_thing'] or '-'}"
            + (f" (Mindestversion: {d['one_thing_min']})" if d["one_thing_min"] else "")
            + (" ✅" if d["one_thing_done"] else ""),
            f"Stimmung {d['mood'] or '-'}, Energie {d['energy'] or '-'}, aufgestanden {d['wake_time'] or '-'}",
            f"Essen: {eaten['kcal']:.0f}/{t['kcal']} kcal, {eaten['protein']:.0f}/{t['protein']} g Eiweiß",
        ]
        wo_today = self.db.q("SELECT type FROM workouts WHERE date=?", (today.isoformat(),))
        if wo_today:
            today_bits.append("Training heute: " + ", ".join(r["type"] for r in wo_today))
        parts.append("Heute: " + " | ".join(today_bits))
        yest = self.db.one("SELECT * FROM days WHERE date=?",
                           ((today - timedelta(days=1)).isoformat(),))
        if yest and (yest["tomorrow"] or yest["one_thing"]):
            parts.append(f"Gestern: EINE={yest['one_thing'] or '-'}"
                         f"{' ✅' if yest['one_thing_done'] else ' ❌'}; Plan für heute: {yest['tomorrow'] or '-'}")
        wo = stats.workouts_week(self.db, today)
        wo_txt = ", ".join(f"{k} {v['n']}x" for k, v in wo.items()) or "keins"
        parts.append(
            f"Letzte 7 Tage: Streak {stats.one_thing_streak(self.db, today)}, "
            f"Stimmung Ø {stats.mood_avg(self.db, today)}, "
            f"Gewicht Ø7 {w['avg7']} (Δ zur Vorwoche {w['delta']}), "
            f"Training: {wo_txt}, "
            f"Handstand-Bestzeit {stats.handstand_best(self.db):.0f}s"
        )
        projs = self.db.q("SELECT * FROM projects WHERE status='aktiv' ORDER BY priority DESC, updated DESC LIMIT 8")
        if projs:
            stale = {p["id"] for p in stats.stale_projects(self.db, today)}
            parts.append("Aktive Projekte:\n" + "\n".join(
                f"- {p['name']}: nächster Schritt '{p['next_step'] or '?'}'"
                + (f", Deadline {p['deadline']}" if p["deadline"] else "")
                + (" ⚠️ seit >5 Tagen kein Update" if p["id"] in stale else "")
                for p in projs))
        ideas = self.db.q("SELECT id, text, status FROM ideas ORDER BY id DESC LIMIT 6")
        if ideas:
            parts.append("Letzte Ideen (id/status): " + "; ".join(
                f"#{i['id']} {i['text'][:60]} [{i['status']}]" for i in ideas))
        if stats.low_mood_days(self.db, today) >= 3:
            parts.append(safety.LOW_MOOD_NOTE)
        msgs = self.db.q("SELECT direction, text FROM messages ORDER BY id DESC LIMIT 8")
        if msgs:
            parts.append("Letzte Nachrichten:\n" + "\n".join(
                f"{'Ich' if m['direction'] == 'in' else 'Coach'}: {m['text'][:300]}"
                for m in reversed(msgs)))
        return "\n\n".join(parts)

    # ----------------------------------------------------------- incoming
    async def handle_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            return await self.command(text)
        self._log_in(text)
        if safety.is_crisis(text):
            return await self.send(safety.CRISIS_MESSAGE, kind="safety")

        prompt = f"{self.context()}\n\nMeine neue Nachricht:\n{text}"
        res = await self.llm.ask(prompts.SYSTEM, prompt, prompts.CHAT_SCHEMA, purpose="chat")
        if not res.ok or not res.data:
            await self._apply_simple(text)
            return await self.send(self._offline_reply(res.error))
        self.apply_extract(res.data.get("extract") or {})
        self._store_ideas(res.data.get("ideas") or [])
        await self.send(res.data.get("reply") or "👍")
        if (res.data.get("extract") or {}).get("wants_meal_suggestion"):
            await self.suggest_meal()
        await self._budget_warnings()

    async def handle_callback(self, data: str) -> None:
        kind, _, rest = data.partition(":")
        if kind == "mood":
            self._log_in(f"[Stimmung {rest}]")
            self.db.update_day(self.today(), mood=int(rest))
            m = int(rest)
            d = self.db.day(self.today())
            if m <= 3:
                msg = "Danke für die Ehrlichkeit. 💛 Heute zählt nur ein Mini-Schritt. Was wäre das Kleinste, das dir guttun würde?"
            elif not d["one_thing"]:
                msg = f"{m}/10 – notiert. Und was ist heute das EINE Wichtige?"
            else:
                msg = f"{m}/10 – notiert. 👍"
            await self.send(msg)
        elif kind == "meal":
            action, _, rid = rest.partition(":")
            if action == "next":
                await self.suggest_meal(force_known=True)
            else:
                await self.send(meals.rate(self.db, int(rid), action, self.now(), self.cfg))
        elif kind == "done":
            self.db.update_day(self.today(), one_thing_done=1)
            await self.send(f"✅ Stark! Streak: {stats.one_thing_streak(self.db, self.now().date())} 🔥")

    # ------------------------------------------------------- data extraction
    def apply_extract(self, ex: dict) -> None:
        today = self.today()
        now = self.now().isoformat(timespec="seconds")
        fields = {k: v for k, v in ex.items() if k in DAY_FIELDS and v not in (None, "")}
        for k in ("mood", "energy"):
            if k in fields:
                try:
                    fields[k] = max(1, min(10, int(fields[k])))
                except (TypeError, ValueError):
                    fields.pop(k)
        self.db.update_day(today, **fields)
        if ex.get("one_thing_done") is True:
            self.db.update_day(today, one_thing_done=1)
        if ex.get("weight_kg"):
            self.db.x("INSERT OR REPLACE INTO weights(date,kg) VALUES(?,?)",
                      (today, float(ex["weight_kg"])))
        for m in ex.get("meals") or []:
            self.log_meal(m.get("name", "?"), m.get("kcal"), m.get("protein"))
        for w in ex.get("workouts") or []:
            self.db.x("INSERT INTO workouts(date,type,minutes,distance_km,handstand_sec,note) "
                      "VALUES(?,?,?,?,?,?)", (today, w.get("type", "sonstiges"), w.get("minutes"),
                                              w.get("distance_km"), w.get("handstand_sec"), w.get("note")))
        for p in ex.get("projects") or []:
            self.upsert_project(p)
        for f in ex.get("idea_feedback") or []:
            self.db.x("UPDATE ideas SET status=? WHERE id=?", (f["status"], int(f["id"])))
        for f in ex.get("facts") or []:
            if f.get("fact"):
                self.db.x("INSERT INTO facts(ts,category,fact) VALUES(?,?,?)",
                          (now, f.get("category"), f["fact"]))

    def log_meal(self, name: str, kcal=None, protein=None) -> None:
        r = self.db.one("SELECT * FROM recipes WHERE lower(name)=lower(?)", (name,))
        if r:
            kcal = kcal if kcal is not None else r["kcal"]
            protein = protein if protein is not None else r["protein"]
            self.db.x("UPDATE recipes SET eaten=eaten+1 WHERE id=?", (r["id"],))
        now = self.now()
        self.db.x("INSERT INTO meals(ts,date,name,kcal,protein,recipe_id) VALUES(?,?,?,?,?,?)",
                  (now.isoformat(timespec="seconds"), now.date().isoformat(), name,
                   kcal or 0, protein or 0, r["id"] if r else None))

    def upsert_project(self, p: dict) -> None:
        now = self.now().isoformat(timespec="seconds")
        name = p["name"].strip()
        row = self.db.one("SELECT * FROM projects WHERE lower(name)=lower(?)", (name,))
        if not row:
            pid = self.db.x("INSERT INTO projects(name,goal,next_step,deadline,status,created,updated) "
                            "VALUES(?,?,?,?,?,?,?)", (name, p.get("goal"), p.get("next_step"),
                                                      p.get("deadline"), p.get("status") or "aktiv", now, now))
            self.db.x("INSERT INTO project_log(project_id,ts,note) VALUES(?,?,?)", (pid, now, "angelegt"))
            return
        upd = {k: p[k] for k in ("goal", "next_step", "deadline", "status") if p.get(k)}
        upd["updated"] = now
        cols = ", ".join(f"{k}=?" for k in upd)
        self.db.x(f"UPDATE projects SET {cols} WHERE id=?", (*upd.values(), row["id"]))
        note = p.get("note") or (f"nächster Schritt: {p['next_step']}" if p.get("next_step") else "Update")
        self.db.x("INSERT INTO project_log(project_id,ts,note) VALUES(?,?,?)", (row["id"], now, note))

    def _store_ideas(self, ideas: list) -> None:
        for i in ideas:
            if i.get("text"):
                self.db.x("INSERT INTO ideas(ts,category,text) VALUES(?,?,?)",
                          (self.now().isoformat(timespec="seconds"), i.get("category"), i["text"]))

    async def _apply_simple(self, text: str) -> None:
        """Minimale Auswertung ohne KI (z. B. 'gewicht 82,4', 'erledigt')."""
        if m := re.search(r"(\d{2,3}[.,]\d)\s*kg", text):
            self.db.x("INSERT OR REPLACE INTO weights(date,kg) VALUES(?,?)",
                      (self.today(), float(m.group(1).replace(",", "."))))
        if re.search(r"\b(erledigt|geschafft|done)\b", text, re.I):
            self.db.update_day(self.today(), one_thing_done=1)

    def _offline_reply(self, error: str) -> str:
        if error == "budget":
            return ("Notiert. 📝 (Das KI-Guthaben für diesen Monat ist fast aufgebraucht – ich antworte "
                    "bis Monatsende mit Vorlagen. Befehle wie /essen, /status und /gewicht funktionieren weiter.)")
        return "Notiert. 📝 (Ich hab gerade keinen Draht zur KI – Befehle wie /status gehen trotzdem.)"

    # ------------------------------------------------------------ commands
    async def command(self, text: str) -> None:
        cmd, _, arg = text[1:].partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        self.db.x("UPDATE checkins SET answered=1 WHERE date=? AND answered=0", (self.today(),))
        if cmd in ("start", "hilfe", "help"):
            return await self.send("Hi, ich bin dein Coach. 👋\n\n" + HELP)
        if cmd == "status":
            return await self.send(self.status_text())
        if cmd == "essen":
            return await self.suggest_meal(wish=arg)
        if cmd == "gewicht":
            try:
                kg = float(arg.replace(",", ".").replace("kg", ""))
            except ValueError:
                return await self.send("Bitte so: /gewicht 82.4")
            self.db.x("INSERT OR REPLACE INTO weights(date,kg) VALUES(?,?)", (self.today(), kg))
            w = stats.weight_trend(self.db, self.now().date())
            return await self.send(f"⚖️ {kg} kg eingetragen. 7-Tage-Schnitt: {w['avg7']} kg"
                                   + (f" (Δ Vorwoche {w['delta']:+})" if w["delta"] is not None else ""))
        if cmd == "projekte":
            rows = self.db.q("SELECT * FROM projects WHERE status!='fertig' ORDER BY status, priority DESC")
            if not rows:
                return await self.send("Noch keine Projekte. Anlegen mit:\n/neu Name | Ziel | nächster Schritt | Deadline")
            return await self.send("\n".join(
                f"{'🟢' if p['status'] == 'aktiv' else '⏸'} *{p['name']}* – {p['goal'] or ''}\n"
                f"   → {p['next_step'] or 'nächster Schritt?'}"
                + (f" (bis {p['deadline']})" if p["deadline"] else "") for p in rows))
        if cmd == "neu":
            parts = [s.strip() for s in arg.split("|")] + [""] * 4
            if not parts[0]:
                return await self.send("Bitte so: /neu Name | Ziel | nächster Schritt | Deadline (optional)")
            self.upsert_project({"name": parts[0], "goal": parts[1] or None,
                                 "next_step": parts[2] or None, "deadline": parts[3] or None})
            return await self.send(f"📁 Projekt *{parts[0]}* angelegt. Ich frag regelmäßig nach.")
        if cmd == "ziel":
            nums = dict(re.findall(r"(kcal|protein)\s*(\d+)", arg.lower()))
            if not nums:
                t = meals.targets(self.db, self.cfg)
                return await self.send(f"Aktuell: {t['kcal']} kcal, {t['protein']} g Eiweiß.\n"
                                       "Ändern: /ziel kcal 2100 protein 160")
            t = meals.targets(self.db, self.cfg)
            t.update({k: int(v) for k, v in nums.items()})
            self.db.set("targets", t)
            return await self.send(f"🎯 Neue Ziele: {t['kcal']} kcal, {t['protein']} g Eiweiß.")
        if cmd == "zutat":
            m = re.match(r"(.+?)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)$", arg)
            if not m:
                return await self.send("Bitte so: /zutat skyr natur 63 11 4 0.2  (pro 100 g: kcal protein kh fett)")
            custom = self.db.get("custom_foods", {}) or {}
            custom[nutrition.norm(m.group(1))] = [float(m.group(i).replace(",", ".")) for i in range(2, 6)]
            self.db.set("custom_foods", custom)
            return await self.send(f"🥫 Zutat '{m.group(1)}' gespeichert.")
        if cmd == "merken":
            if arg:
                self.db.x("INSERT INTO facts(ts,category,fact) VALUES(?,?,?)",
                          (self.now().isoformat(timespec="seconds"), "manuell", arg))
                return await self.send("🧠 Gemerkt.")
            return await self.send("Bitte so: /merken Ich trainiere am liebsten abends.")
        if cmd == "ruhe":
            if arg.lower() in ("aus", "off", "0"):
                self.db.set("quiet_until", None)
                return await self.send("🔔 Ich bin wieder da.")
            try:
                hours = float(arg.replace(",", ".")) if arg else 4
            except ValueError:
                hours = 4
            until = self.now() + timedelta(hours=hours)
            self.db.set("quiet_until", until.isoformat())
            return await self.send(f"🔕 Ruhe bis {until:%H:%M} ({until:%d.%m.}).")
        if cmd == "woche":
            return await self.weekly_review()
        if cmd == "kosten":
            c = self.llm.month_cost()
            n = self.db.one("SELECT COUNT(*) n FROM llm_usage WHERE ts LIKE ?",
                            (self.now().strftime("%Y-%m") + "%",))["n"]
            return await self.send(
                f"💰 Diesen Monat: {c:.2f} $ von {self.cfg.monthly_budget_usd:.0f} $ "
                f"({c / self.cfg.monthly_budget_usd * 100:.0f} %), {n} KI-Aufrufe.\n"
                "_Gezählt wird nur, was der Coach verbraucht – andere claude -p Nutzung "
                "zieht vom selben Guthaben ab._")
        if cmd == "checkin":
            return await self.run_checkin(arg or "morgen", force=True)
        if cmd == "erledigt":
            return await self.handle_callback("done:1")
        return await self.send("Den Befehl kenne ich nicht. /hilfe zeigt alle.")

    def status_text(self) -> str:
        today = self.now().date()
        d = self.db.day(today.isoformat())
        t = meals.targets(self.db, self.cfg)
        e = meals.eaten_today(self.db, today.isoformat())
        w = stats.weight_trend(self.db, today)
        return "\n".join([
            f"📅 *{WEEKDAYS_DE[today.weekday()]}*",
            f"🎯 Das EINE: {d['one_thing'] or '–'} {'✅' if d['one_thing_done'] else ''}",
            f"🔥 Streak: {stats.one_thing_streak(self.db, today)} Tage",
            f"🙂 Stimmung {d['mood'] or '–'} · ⚡ Energie {d['energy'] or '–'}",
            f"🍽 {e['kcal']:.0f}/{t['kcal']} kcal · {e['protein']:.0f}/{t['protein']} g Eiweiß",
            f"⚖️ Ø7: {w['avg7'] or '–'} kg" + (f" (Δ {w['delta']:+})" if w["delta"] is not None else ""),
            f"🤸 Handstand-Bestzeit: {stats.handstand_best(self.db):.0f} s",
        ])

    # --------------------------------------------------------------- meals
    async def suggest_meal(self, wish: str = "", force_known: bool = False) -> None:
        now = self.now()
        best, rem, slot = meals.pick_known(self.db, self.cfg, now)
        explore = (not force_known) and (wish or best is None or random.random() < meals.EXPLORE_RATE)
        if explore and self.llm.budget_ok():
            facts = "\n".join(f"- {f['fact']}" for f in self.db.q(
                "SELECT fact FROM facts WHERE active=1 ORDER BY id DESC LIMIT 20"))
            profile = f"{self.db.get('taste_profile') or ''}\n{facts}"
            res = await self.llm.ask(
                "Du bist ein pragmatischer Ernährungscoach. Antworte nur im verlangten JSON.",
                meals.recipe_prompt(self.db, rem, slot, wish, profile),
                meals.RECIPE_SCHEMA, purpose="recipe")
            if res.ok and res.data:
                r = res.data
                name = r["name"]
                if self.db.one("SELECT 1 FROM recipes WHERE name=?", (name,)):
                    name = f"{name} ({now:%d.%m.})"
                rid = nutrition.add_recipe(self.db, name, r.get("slot", slot), r.get("minutes", 15),
                                           r.get("tags", []), r["ingredients"], r["instructions"],
                                           source="ki", estimated=r.get("estimated"))
                row = self.db.one("SELECT * FROM recipes WHERE id=?", (rid,))
                meals.mark_suggested(self.db, rid, now)
                return await self.send("✨ Neue Idee:\n" + meals.format_recipe(row, rem, r.get("pitch", "")),
                                       meals.rating_buttons(rid), kind="meal")
        if best is None:
            return await self.send("Ich hab noch keine Rezepte gespeichert.")
        meals.mark_suggested(self.db, best["id"], now)
        await self.send(meals.format_recipe(best, rem), meals.rating_buttons(best["id"]), kind="meal")

    # ------------------------------------------------------------ check-ins
    def quiet(self) -> bool:
        q = self.db.get("quiet_until")
        return bool(q) and datetime.fromisoformat(q) > self.now()

    def needs_attention(self, name: str) -> bool:
        """Für optionale Check-ins: nur melden, wenn es etwas zu tun gibt."""
        today = self.now().date()
        d = self.db.day(today.isoformat())
        if name == "vormittag":
            return not d["one_thing_done"]
        if name == "mittag":
            e = meals.eaten_today(self.db, today.isoformat())
            return e["n"] == 0 or bool(stats.stale_projects(self.db, today)) or not d["one_thing_done"]
        if name == "bewegung":
            return not self.db.one("SELECT 1 FROM workouts WHERE date=?", (today.isoformat(),))
        return True

    async def run_checkin(self, name: str, force: bool = False) -> None:
        today = self.today()
        if not force:
            if self.quiet():
                return
            if name in self.cfg.optional_checkins and not self.needs_attention(name):
                self.db.x("INSERT OR IGNORE INTO checkins(date,name,sent_ts,answered,followed_up) "
                          "VALUES(?,?,?,1,1)", (today, name, self.now().isoformat()))
                return
        goal = prompts.CHECKIN_GOALS.get(name, f"Check-in '{name}'")
        prompt = (f"{self.context(checkin=name)}\n\nAUFGABE: Schreib mir jetzt von dir aus "
                  f"die Nachricht für diesen Check-in. {goal}\n"
                  "'extract' bleibt leer (ich habe nichts Neues geschrieben).")
        res = await self.llm.ask(prompts.SYSTEM, prompt, prompts.CHAT_SCHEMA, purpose=f"checkin:{name}")
        if res.ok and res.data and res.data.get("reply"):
            text = res.data["reply"]
            self._store_ideas(res.data.get("ideas") or [])
        else:
            text = random.choice(FALLBACK.get(name, ["Wie läuft's?"]))
        buttons = MOOD_BUTTONS if name == "morgen" else None
        if name in ("abend", "vormittag", "mittag") and not self.db.day(today)["one_thing_done"] \
                and self.db.day(today)["one_thing"]:
            buttons = [[("✅ Das EINE erledigt", "done:1")]]
        self.db.x("INSERT OR REPLACE INTO checkins(date,name,sent_ts,answered,followed_up) "
                  "VALUES(?,?,?,0,0)", (today, name, self.now().isoformat()))
        await self.send(text, buttons, kind=f"checkin:{name}")
        await self._budget_warnings()

    async def followups(self) -> None:
        """Einmal nachhaken, wenn ein Check-in ~30 Min unbeantwortet ist."""
        if self.quiet():
            return
        now = self.now()
        if now.hour >= 23 or now.hour < 6:
            return
        rows = self.db.q("SELECT * FROM checkins WHERE date=? AND answered=0 AND followed_up=0",
                         (self.today(),))
        for r in rows:
            if now - datetime.fromisoformat(r["sent_ts"]) >= timedelta(minutes=self.cfg.followup_minutes):
                self.db.x("UPDATE checkins SET followed_up=1 WHERE id=?", (r["id"],))
                await self.send(random.choice(FOLLOWUPS), kind="followup")

    # -------------------------------------------------------- weekly review
    async def weekly_review(self) -> None:
        today = self.now().date()
        summary = stats.week_summary(self.db, today)
        ratings = self.db.q(
            "SELECT r.name, s.rating FROM meal_suggestions s JOIN recipes r ON r.id=s.recipe_id "
            "WHERE s.rating IS NOT NULL AND s.ts > ? ORDER BY s.id DESC LIMIT 30",
            ((today - timedelta(days=7)).isoformat(),))
        eaten = self.db.q("SELECT name, COUNT(*) n FROM meals WHERE date > ? GROUP BY name "
                          "ORDER BY n DESC LIMIT 15", ((today - timedelta(days=7)).isoformat(),))
        ideas = self.db.q("SELECT text, status FROM ideas WHERE ts > ?",
                          ((today - timedelta(days=7)).isoformat(),))
        rat_txt = ", ".join(f"{r['name']}={r['rating']}" for r in ratings) or "-"
        eat_txt = ", ".join(f"{r['name']} {r['n']}x" for r in eaten) or "-"
        idea_txt = ", ".join(f"{i['text'][:40]} [{i['status']}]" for i in ideas) or "-"
        prompt = (
            f"{self.context()}\n\nZAHLEN DER WOCHE:\n{summary}\n\n"
            f"Essensbewertungen: {rat_txt}\n"
            f"Gegessen: {eat_txt}\n"
            f"Ideen der Woche: {idea_txt}\n\n"
            f"AUFGABE: {prompts.WEEKLY_TASK}"
        )
        res = await self.llm.ask(prompts.SYSTEM, prompt, prompts.WEEKLY_SCHEMA, smart=True, purpose="weekly")
        if res.ok and res.data:
            if res.data.get("taste_profile"):
                self.db.set("taste_profile", res.data["taste_profile"])
            if res.data.get("coach_notes"):
                self.db.set("coach_notes", res.data["coach_notes"])
            self._store_ideas(res.data.get("ideas") or [])
            text = "📊 *Wochenrückblick*\n\n" + res.data["reply"]
        else:
            text = "📊 *Wochenrückblick*\n\n" + summary
        self.db.set("last_weekly", today.isoformat())
        await self.send(text, kind="weekly")

    # ------------------------------------------------------------- budget
    async def _budget_warnings(self) -> None:
        share = self.llm.budget_share()
        month = self.now().strftime("%Y-%m")
        for level in (0.7, 0.9):
            key = f"budget_warn_{month}_{int(level * 100)}"
            if share >= level and not self.db.get(key):
                self.db.set(key, True)
                await self.send(
                    f"⚠️ Hinweis: {share * 100:.0f} % des KI-Guthabens ({self.cfg.monthly_budget_usd:.0f} $) "
                    "für diesen Monat sind verbraucht. Ab 95 % antworte ich mit Vorlagen, "
                    "bis das Guthaben sich erneuert.", kind="system")

    # ------------------------------------------------------------ scheduler
    async def tick(self) -> None:
        """Wird ca. alle 20 s aufgerufen."""
        now = self.now()
        hhmm = now.strftime("%H:%M")
        name = self.cfg.checkins.get(hhmm)
        if name and not self.db.one("SELECT 1 FROM checkins WHERE date=? AND name=?",
                                    (self.today(), name)):
            await self.run_checkin(name)
        await self.followups()
        day_code, _, at = self.cfg.weekly_review.partition(" ")
        if (WEEKDAY_CODES[now.weekday()] == day_code and hhmm == at
                and self.db.get("last_weekly") != self.today() and not self.quiet()):
            await self.weekly_review()
