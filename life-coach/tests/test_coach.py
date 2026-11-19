import asyncio
import json
from datetime import date, datetime, timedelta

import pytest

from coach import meals, stats
from coach.coach import Coach
from coach.config import Config, parse_checkins
from coach.db import DB
from coach.llm import LLM, LLMResult


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, text, buttons=None):
        self.sent.append((text, buttons))


class ScriptedLLM(LLM):
    """LLM, das vorgegebene JSON-Antworten liefert und Aufrufe mitschreibt."""

    def __init__(self, cfg, db, responses=None, cost=0.01):
        super().__init__(cfg, db)
        self.responses = list(responses or [])
        self.calls = []
        self.cost = cost

    async def _claude(self, system, prompt, schema, model):
        self.calls.append({"prompt": prompt, "model": model, "schema": schema})
        data = self.responses.pop(0) if self.responses else {"reply": "ok"}
        return LLMResult(True, data, json.dumps(data), cost_usd=self.cost)


def make(responses=None, cost=0.01, **cfgkw):
    cfg = Config(db_path=":memory:", **cfgkw)
    cfg.checkins = parse_checkins("06:30=morgen,10:00=vormittag,21:30=abend")
    db = DB(":memory:")
    llm = ScriptedLLM(cfg, db, responses, cost)
    ch = FakeChannel()
    return Coach(cfg, db, llm, ch), llm, ch


def run(coro):
    return asyncio.run(coro)


def test_parse_checkins():
    assert parse_checkins("6:30=morgen, 21:30=abend") == {"06:30": "morgen", "21:30": "abend"}


def test_chat_extracts_data():
    coach, llm, ch = make([{
        "reply": "Super, los geht's!",
        "extract": {
            "mood": 7, "energy": 6, "one_thing": "Bewerbung schreiben",
            "weight_kg": 84.2,
            "meals": [{"name": "Topfen-Beeren-Bowl"}],
            "workouts": [{"type": "handstand", "handstand_sec": 25}],
            "projects": [{"name": "Website", "next_step": "Startseite skizzieren"}],
            "facts": [{"fact": "Mag keine Pilze", "category": "essen"}],
        },
        "ideas": [{"text": "10 Min Spaziergang nach dem Mittagessen"}],
    }])
    run(coach.handle_text("Morgen! 7/10, heute Bewerbung, 84,2 kg, Topfen-Bowl gegessen"))
    assert ch.sent[-1][0] == "Super, los geht's!"
    d = coach.db.day(coach.today())
    assert d["mood"] == 7 and d["one_thing"] == "Bewerbung schreiben"
    assert coach.db.one("SELECT kg FROM weights")["kg"] == 84.2
    meal = coach.db.one("SELECT * FROM meals")
    assert meal["kcal"] > 200 and meal["recipe_id"]  # Makros aus Rezept übernommen
    assert stats.handstand_best(coach.db) == 25
    assert coach.db.one("SELECT next_step FROM projects WHERE name='Website'")[0] == "Startseite skizzieren"
    assert coach.db.one("SELECT fact FROM facts")[0] == "Mag keine Pilze"
    assert coach.db.one("SELECT COUNT(*) FROM ideas")[0] == 1
    # Kosten werden geloggt
    assert coach.db.one("SELECT SUM(cost_usd) FROM llm_usage")[0] == pytest.approx(0.01)
    # Kontext ist kompakt (kein riesiger Verlauf)
    assert len(llm.calls[0]["prompt"]) < 6000


def test_crisis_bypasses_llm():
    coach, llm, ch = make()
    run(coach.handle_text("ich will nicht mehr leben"))
    assert "142" in ch.sent[-1][0]
    assert llm.calls == []


def test_commands_work_without_llm():
    coach, llm, ch = make()
    run(coach.handle_text("/gewicht 83,5"))
    assert "83.5" in ch.sent[-1][0]
    run(coach.handle_text("/neu Gitarre | 3 Songs lernen | Akkorde üben | 2026-12-31"))
    assert coach.db.one("SELECT goal FROM projects WHERE name='Gitarre'")[0] == "3 Songs lernen"
    run(coach.handle_text("/ziel kcal 2100 protein 165"))
    assert meals.targets(coach.db, coach.cfg) == {"kcal": 2100, "protein": 165}
    run(coach.handle_text("/status"))
    assert "Streak" in ch.sent[-1][0]
    assert llm.calls == []


def test_meal_suggestion_learns(monkeypatch):
    coach, llm, ch = make()
    monkeypatch.setattr(meals, "EXPLORE_RATE", 0.0)
    run(coach.suggest_meal())
    text, buttons = ch.sent[-1]
    rid = int(buttons[0][0][1].split(":")[2])
    # 3x abgelehnt -> wird nicht mehr vorgeschlagen
    for _ in range(3):
        run(coach.handle_callback(f"meal:dislike:{rid}"))
    for _ in range(15):
        run(coach.suggest_meal(force_known=True))
        assert int(ch.sent[-1][1][0][0][1].split(":")[2]) != rid
    # gegessen -> wird als Mahlzeit gezählt
    rid2 = int(ch.sent[-1][1][0][0][1].split(":")[2])
    run(coach.handle_callback(f"meal:eaten:{rid2}"))
    assert meals.eaten_today(coach.db, coach.today())["n"] == 1
    assert llm.calls == []  # bekannte Rezepte kosten nichts


def test_new_recipe_from_llm_computes_macros():
    coach, llm, ch = make([{
        "name": "Huhn-Wrap Spezial", "minutes": 10, "slot": "mittag", "tags": ["schnell"],
        "ingredients": [{"item": "Hühnerbrust", "grams": 200}, {"item": "wrap vollkorn", "grams": 65}],
        "instructions": "Braten, einwickeln.",
        "estimated": {"kcal": 999, "protein": 1, "carbs": 1, "fat": 1},
        "pitch": "Schnell und viel Eiweiß.",
    }])
    run(coach.suggest_meal(wish="schnell"))
    r = coach.db.one("SELECT * FROM recipes WHERE name='Huhn-Wrap Spezial'")
    assert r["macros_verified"] == 1
    assert r["protein"] == pytest.approx(200 * 0.23 + 65 * 0.09, abs=0.2)  # aus Tabelle, nicht geraten
    assert "Neue Idee" in ch.sent[-1][0]


def test_checkin_followup_once(monkeypatch):
    coach, llm, ch = make([{"reply": "Guten Morgen! Was ist heute das EINE?"}])
    base = datetime(2026, 11, 20, 6, 30, tzinfo=coach.cfg.tz)
    monkeypatch.setattr(coach, "now", lambda: base)
    run(coach.tick())
    assert ch.sent[-1][0].startswith("Guten Morgen")
    assert ch.sent[-1][1]  # Stimmungs-Buttons
    run(coach.tick())  # gleiche Minute -> nicht doppelt
    assert len(ch.sent) == 1
    monkeypatch.setattr(coach, "now", lambda: base + timedelta(minutes=31))
    run(coach.tick())
    assert len(ch.sent) == 2  # einmal nachgehakt
    monkeypatch.setattr(coach, "now", lambda: base + timedelta(minutes=70))
    run(coach.tick())
    assert len(ch.sent) == 2  # nicht nochmal


def test_answer_cancels_followup(monkeypatch):
    coach, llm, ch = make([{"reply": "Morgen!"}, {"reply": "Top."}])
    base = datetime(2026, 11, 20, 6, 30, tzinfo=coach.cfg.tz)
    monkeypatch.setattr(coach, "now", lambda: base)
    run(coach.tick())
    run(coach.handle_callback("mood:8"))
    monkeypatch.setattr(coach, "now", lambda: base + timedelta(minutes=40))
    run(coach.tick())
    assert len(ch.sent) == 2  # Check-in + Antwort auf Button, kein Nachhaken


def test_optional_checkin_skipped_when_done(monkeypatch):
    coach, llm, ch = make(optional_checkins={"vormittag"})
    base = datetime(2026, 11, 20, 10, 0, tzinfo=coach.cfg.tz)
    monkeypatch.setattr(coach, "now", lambda: base)
    coach.db.update_day("2026-11-20", one_thing="x", one_thing_done=1)
    run(coach.tick())
    assert ch.sent == [] and llm.calls == []


def test_quiet_mode(monkeypatch):
    coach, llm, ch = make()
    base = datetime(2026, 11, 20, 6, 0, tzinfo=coach.cfg.tz)
    monkeypatch.setattr(coach, "now", lambda: base)
    run(coach.handle_text("/ruhe 2"))
    monkeypatch.setattr(coach, "now", lambda: base + timedelta(minutes=30))
    run(coach.tick())
    assert len(ch.sent) == 1  # nur die Bestätigung


def test_budget_stop_uses_templates(monkeypatch):
    coach, llm, ch = make(cost=19.5)
    run(coach.handle_text("hallo"))  # kostet 19.5 -> 97.5 %
    assert any("90 %" in t or "Guthabens" in t for t, _ in ch.sent)
    n = len(llm.calls)
    run(coach.handle_text("noch was"))
    assert len(llm.calls) == n  # kein weiterer KI-Aufruf
    assert "Vorlagen" in ch.sent[-1][0]


def test_streak_never_miss_twice():
    db = DB(":memory:")
    t = date(2026, 11, 20)
    for i, done in enumerate([1, 1, 0, 1, 1]):  # vor 4 Tagen ... heute
        db.update_day((t - timedelta(days=4 - i)).isoformat(), one_thing_done=done)
    assert stats.one_thing_streak(db, t) == 4  # ein Aussetzer bricht nicht
    db.update_day((t - timedelta(days=5)).isoformat(), one_thing_done=0)
    db.update_day((t - timedelta(days=6)).isoformat(), one_thing_done=0)
    db.update_day((t - timedelta(days=7)).isoformat(), one_thing_done=1)
    assert stats.one_thing_streak(db, t) == 4  # zwei Aussetzer beenden ihn


def test_weekly_review_updates_profile():
    coach, llm, ch = make([{"reply": "Starke Woche!", "taste_profile": "liebt Topfen",
                            "coach_notes": "morgens schwer"}])
    run(coach.weekly_review())
    assert coach.db.get("taste_profile") == "liebt Topfen"
    assert llm.calls[0]["model"] == coach.cfg.model_smart
    assert "Wochenrückblick" in ch.sent[-1][0]


def test_claude_cli_invocation(tmp_path):
    """Prüft Aufruf + Parsing mit einem Platzhalter statt der echten CLI."""
    fake = tmp_path / "claude"
    log = tmp_path / "args.json"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}, open({str(log)!r}, 'w'))\n"
        "print(json.dumps({'type': 'result', 'is_error': False, 'result': '',"
        " 'structured_output': {'reply': 'Hallo!'}, 'total_cost_usd': 0.0042,"
        " 'usage': {'input_tokens': 1200, 'output_tokens': 80}}))\n")
    fake.chmod(0o755)
    cfg = Config(db_path=":memory:", claude_bin=str(fake))
    db = DB(":memory:")
    llm = LLM(cfg, db)
    from coach import prompts
    res = run(llm.ask("SYS", "PROMPT", prompts.CHAT_SCHEMA))
    assert res.ok and res.data == {"reply": "Hallo!"}
    args = json.load(open(log))
    argv = args["argv"]
    assert args["stdin"] == "PROMPT"
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--tools") + 1] == ""
    assert "--json-schema" in argv and "--no-session-persistence" in argv
    assert "--bare" not in argv  # --bare würde den Abo-Login ignorieren
    row = db.one("SELECT * FROM llm_usage")
    assert row["cost_usd"] == pytest.approx(0.0042) and row["input_tokens"] == 1200
