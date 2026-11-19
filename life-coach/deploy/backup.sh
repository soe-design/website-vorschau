#!/usr/bin/env bash
# Konsistente Sicherung der Datenbank (auch im laufenden Betrieb).
# Beispiel-Cronjob: 0 3 * * * /pfad/life-coach/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
.venv/bin/python - <<'PY'
import sqlite3, datetime
src = sqlite3.connect("data/coach.db")
dst = sqlite3.connect(f"backups/coach-{datetime.date.today()}.db")
src.backup(dst); dst.close(); src.close()
PY
ls -1t backups/coach-*.db | tail -n +31 | xargs -r rm --   # 30 Tage behalten
echo "Backup ok"
