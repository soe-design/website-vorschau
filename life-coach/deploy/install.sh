#!/usr/bin/env bash
# Installiert den Coach im aktuellen Ordner und richtet einen systemd-Dienst ein.
# Aufruf (als der Benutzer, der in Claude Code eingeloggt ist – NICHT als root):
#   ./deploy/install.sh            # venv + Dienst
#   ./deploy/install.sh --no-service
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
USER_NAME="$(id -un)"

command -v python3 >/dev/null || { echo "python3 fehlt"; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3,11))' || { echo "Python >= 3.11 nötig"; exit 1; }

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo ">> .env angelegt – bitte TELEGRAM_BOT_TOKEN eintragen."; }
mkdir -p data

CLAUDE_PATH="$(command -v claude || true)"
if [ -z "$CLAUDE_PATH" ]; then
  echo "!! 'claude' nicht gefunden. Installieren: https://code.claude.com/docs  danach 'claude' einmal starten und einloggen."
else
  echo ">> claude gefunden: $CLAUDE_PATH ($("$CLAUDE_PATH" --version 2>/dev/null || echo '?'))"
fi

[ "${1:-}" = "--no-service" ] && { echo "Fertig. Test: .venv/bin/python -m coach.main --channel console"; exit 0; }

UNIT=/etc/systemd/system/life-coach.service
EXTRA_PATH="$(dirname "${CLAUDE_PATH:-/usr/local/bin/claude}")"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@DIR@|$DIR|g" -e "s|@EXTRA_PATH@|$EXTRA_PATH|g" \
  deploy/life-coach.service.template | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now life-coach
echo ">> Dienst läuft. Logs: journalctl -u life-coach -f"
