# Life-Coach 🧭

Persönlicher KI-Coach, der **von sich aus** schreibt: Aufstehen, das EINE Wichtige am Tag,
Projekte, Bewegung, Essen, Tagesbilanz und ein Wochenrückblick. Er lernt dazu (Fakten über dich,
Essensbewertungen, Geschmacksprofil).

- **KI:** ausschließlich über die offizielle Claude Code CLI (`claude -p`) mit deinem Pro-Abo.
  Kein API-Key, keine Tokens auslesen. Jeder Aufruf wird mit Kosten geloggt (`/kosten`).
- **Kanal:** Telegram (kostenlos, Buttons) oder Konsole zum Testen. Austauschbar über `coach/channels/`.
- **Daten:** eine SQLite-Datei `data/coach.db`.
- **Zeitzone:** Europe/Vienna.

## Schnellstart (lokal testen, ohne Telegram)

```bash
./deploy/install.sh --no-service
.venv/bin/python -m coach.main --channel console --fake   # ohne Claude
.venv/bin/python -m coach.main --channel console          # mit Claude (verbraucht Guthaben)
```
In der Konsole drückst du Buttons mit `#1`, `#2` … und testest Check-ins mit `/checkin morgen`.

## Telegram einrichten (5 Minuten)

1. In Telegram **@BotFather** öffnen, `/newbot` schicken, Namen vergeben und das Token kopieren.
2. Das Token in `.env` bei `TELEGRAM_BOT_TOKEN=` eintragen, `CHANNEL=telegram`.
3. Den Coach starten und deinem Bot eine Nachricht schicken. Er antwortet mit deiner **Chat-ID**.
4. Die Chat-ID bei `TELEGRAM_CHAT_ID=` eintragen und neu starten. Ab jetzt redet er nur mit dir.

## Als Dienst (startet nach Reboot automatisch)

```bash
./deploy/install.sh          # als dein normaler Benutzer (der in `claude` eingeloggt ist)
journalctl -u life-coach -f  # Logs
sudo systemctl restart life-coach
```

## Auf einen anderen Rechner umziehen (z. B. auf s1)

Alles, was zählt, sind **der Code, `.env` und `data/coach.db`**.

```bash
# auf dem alten Rechner
sudo systemctl stop life-coach                       # falls als Dienst
scp .env data/coach.db s1:/tmp/

# auf s1
git clone <repo> ~/life-coach && cd ~/life-coach
claude                      # einmal starten und mit deinem Account einloggen, dann beenden
mkdir -p data && mv /tmp/.env . && mv /tmp/coach.db data/
./deploy/install.sh
```
Wichtig: Den Bot nie auf zwei Rechnern gleichzeitig laufen lassen, sonst kommen Nachrichten doppelt.

Backup: `deploy/backup.sh`, z. B. täglich per Cron.

## Befehle im Chat

| Befehl | Was |
|---|---|
| `/status` | das EINE, Streak, Kalorien, Gewichtstrend |
| `/essen [wunsch]` | Mahlzeit-Vorschlag mit Bewertungs-Buttons |
| `/gewicht 82.4` | Gewicht eintragen (Trend = 7-Tage-Schnitt) |
| `/projekte`, `/neu Name \| Ziel \| Schritt \| Deadline` | Projekte |
| `/ziel kcal 2100 protein 160` | Ernährungsziele |
| `/zutat name kcal protein kh fett` | eigene Zutat (pro 100 g), verbessert die Makro-Berechnung |
| `/merken …` | dauerhafte Info über dich |
| `/ruhe [h]` / `/ruhe aus` | Pause |
| `/woche` | Wochenrückblick sofort |
| `/kosten` | KI-Verbrauch diesen Monat |
| `/erledigt` | das EINE als erledigt markieren |

Alles andere schreibst du einfach als normalen Text, z. B. „Gerade 5 km gelaufen, Stimmung 7, Mittag Hühner-Reis“.
Claude zieht die Daten automatisch heraus.

## Wie er spart

- Routine läuft auf `haiku`, nur der Wochenrückblick auf `sonnet` (einstellbar in `.env`).
- Pro Aufruf geht nur eine **kompakte Zusammenfassung** aus der DB mit (meist unter 1.500 Tokens), nicht der ganze Verlauf.
- Eigener System-Prompt, keine Tools, keine MCP-Server, keine Projekt-Settings und ein leeres Arbeitsverzeichnis. Das spart den großen Claude-Code-Standard-Prompt.
- Ohne KI laufen: Streaks, Statistik, Nachhaken, Befehle und Vorschläge **bekannter** Rezepte.
- Warnungen bei 70 % und 90 % des Monatsbudgets. Ab 95 % schickt er Vorlagen statt KI-Text.

## Wie er beim Essen dazulernt

- Bekannte Rezepte wählt Python lokal aus: passend zu den offenen Makros des Tages, zur Tageszeit und zu deinen 👍/👎.
- Etwa 20 % der Vorschläge (und jeder `/essen <wunsch>`) sind **neue Ideen von Claude**. Die Makros dazu werden möglichst aus
  der Nährwert-Tabelle berechnet, nicht geraten.
- Dreimal 👎 heißt, das Rezept kommt nicht mehr. „✅ gegessen“ trägt es direkt als Mahlzeit ein.
- Beim Wochenrückblick schreibt Claude dein **Geschmacksprofil** und Coach-Notizen fort.

## Sicherheit

Krisenwörter werden **ohne KI** erkannt, dann kommen sofort Hilfsnummern (Telefonseelsorge 142, Notruf 144).
Bei mehreren Tagen mit sehr niedriger Stimmung spricht der Coach das behutsam an. Er ist kein Ersatz für Therapie.

## Entwicklung

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q
```

Neuer Kanal (SMS, WhatsApp): eine Klasse mit `send(text, buttons)` und `run(on_text, on_button, tick)`
in `coach/channels/` anlegen und in `coach/main.py` eintragen.
