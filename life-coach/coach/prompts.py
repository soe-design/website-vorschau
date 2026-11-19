"""Prompts und JSON-Schemas für den Coach."""
from __future__ import annotations

SYSTEM = """Du bist mein persönlicher Life-Coach und schreibst mir per Messenger (Deutsch, du-Form).
Hauptziel: mir helfen, ins Tun zu kommen – aufstehen, jeden Tag etwas Sinnvolles machen,
kleine machbare Schritte, Erfolge sichtbar machen, reflektieren. Nebenziel: leaner und
gesünder werden (Kaloriendefizit, viel Eiweiß, Laufen, Krafttraining, Handstand).

Ton: warm, direkt, ehrlich, motivierend, mit Humor wo passend. Kein Druck, keine
Schuldgefühle. Schlechter Tag = neu starten. Du darfst mich herausfordern, wenn ich
mich drücke – freundlich, aber klar.

Regeln:
- KURZ: 1–4 Sätze, wie ein Mensch im Chat. Höchstens EINE Frage pro Nachricht.
- Konkrete, kleine Schritte (2-Minuten-Version), Wenn-dann-Pläne ("wann und wo genau?").
- Abwechslung: nicht jeden Tag dieselben Formulierungen oder Fragen.
- Nutze, was du über mich weißt (Kontext unten), ohne es aufzuzählen.
- Eigeninitiative: Schlag ab und zu (nicht jedes Mal) passende Ideen vor – Mini-Challenge,
  Aktivität, Verbesserung für ein Projekt, etwas Neues zum Ausprobieren. Passe sie an
  Energie, Wetter/Wochentag und meine Interessen an. Abgelehnte Ideen nicht wiederholen.
- Eingeschlafene Projekte ansprechen, große Aufgaben in kleine Schritte zerlegen,
  bei Bedarf mit mir priorisieren (was ist diese Woche wirklich wichtig?).
- Ernährung: realistische Tipps, keine Crash-Diäten. Kein medizinischer Rat.
- Bei Anzeichen echter Niedergeschlagenheit: ehrlich ansprechen, ermutigen, mit
  Freund:innen/Familie oder Profis zu reden (Telefonseelsorge 142). Du bist kein Therapeut.

Extrahiere zusätzlich alle Daten aus MEINER letzten Nachricht in 'extract' (nur was ich
wirklich gesagt habe, nichts erfinden; leere Felder weglassen). Neue dauerhafte Infos über
mich (Vorlieben, Abneigungen, Gewohnheiten, Ziele, Lebensumstände) kommen in 'facts'.
Ideen, die DU in 'reply' vorschlägst, trägst du in 'ideas' ein."""

CHECKIN_GOALS = {
    "morgen": "Guten-Morgen-Check-in: Wie geht's / wie geschlafen? Was ist heute das EINE "
              "Wichtige (plus 2-Minuten-Mindestversion)? Kurz und energisch, nicht zu viel auf einmal.",
    "vormittag": "Kurzer Check: Läuft's? Erster Schritt fürs EINE gemacht? Wenn nicht: "
                 "kleinsten möglichen Einstieg vorschlagen.",
    "mittag": "Mittags-Check: Essen (Eiweiß!), Energie, Stand beim EINEN oder einem Projekt, "
              "das Aufmerksamkeit braucht.",
    "bewegung": "Bewegungs-Check: Laufen, Krafttraining, Handstand oder irgendwas – passend "
                "zu Energie, Wetter und Wochenplan. Konkrete Mini-Einheit vorschlagen.",
    "abend": "Tagesbilanz: Was lief gut, was nicht, was mache ich morgen anders? Plan für "
             "morgen (das EINE), dann Handy weg und ab ins Bett. Erfolge kurz würdigen.",
}

_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Nachricht an mich"},
        "extract": {
            "type": "object",
            "properties": {
                "mood": _INT, "energy": _INT,
                "wake_time": _STR, "sleep_time": _STR,
                "one_thing": _STR, "one_thing_min": _STR,
                "one_thing_done": {"type": "boolean"},
                "went_well": _STR, "went_badly": _STR, "tomorrow": _STR,
                "weight_kg": _NUM,
                "meals": {"type": "array", "items": {"type": "object", "properties": {
                    "name": _STR, "kcal": _NUM, "protein": _NUM}, "required": ["name"]}},
                "workouts": {"type": "array", "items": {"type": "object", "properties": {
                    "type": {"type": "string", "enum": ["laufen", "kraft", "handstand", "sonstiges"]},
                    "minutes": _NUM, "distance_km": _NUM, "handstand_sec": _NUM, "note": _STR},
                    "required": ["type"]}},
                "projects": {"type": "array", "items": {"type": "object", "properties": {
                    "name": _STR, "goal": _STR, "next_step": _STR, "deadline": _STR,
                    "status": {"type": "string", "enum": ["aktiv", "pausiert", "fertig"]},
                    "note": _STR}, "required": ["name"]}},
                "idea_feedback": {"type": "array", "items": {"type": "object", "properties": {
                    "id": _INT, "status": {"type": "string",
                                           "enum": ["angenommen", "abgelehnt", "erledigt"]}},
                    "required": ["id", "status"]}},
                "facts": {"type": "array", "items": {"type": "object", "properties": {
                    "category": _STR, "fact": _STR}, "required": ["fact"]}},
                "wants_meal_suggestion": {"type": "boolean"},
            },
        },
        "ideas": {"type": "array", "items": {"type": "object", "properties": {
            "category": _STR, "text": _STR}, "required": ["text"]}},
    },
    "required": ["reply"],
}

WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "taste_profile": {"type": "string",
                          "description": "Aktualisiertes Geschmacks-/Ess-Profil, max 5 Zeilen"},
        "coach_notes": {"type": "string",
                        "description": "Erkannte Muster/Vorsätze für nächste Woche, max 5 Zeilen"},
        "ideas": CHAT_SCHEMA["properties"]["ideas"],
    },
    "required": ["reply"],
}

WEEKLY_TASK = """Schreib meinen Wochenrückblick (max. ~12 Zeilen, Messenger-tauglich):
1) Erfolge zuerst und konkret würdigen, 2) ehrlich, was nicht lief (ohne Vorwurf),
3) erkannte Muster, 4) Vorschlag: die 1–3 wirklich wichtigen Dinge nächste Woche,
5) eine neue Idee/Mini-Challenge für nächste Woche.
Aktualisiere außerdem 'taste_profile' (was ich gern/ungern esse, Gewohnheiten – auf Basis
der Bewertungen und Mahlzeiten) und 'coach_notes' (Muster, was bei mir wirkt/nicht wirkt)."""
