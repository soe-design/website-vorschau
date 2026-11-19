"""Konfiguration – alles kommt aus .env bzw. Umgebungsvariablen."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv ist optional
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CHECKINS = (
    "06:30=morgen,10:00=vormittag,13:00=mittag,18:00=bewegung,21:30=abend"
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    channel: str = "console"            # console | telegram
    telegram_token: str = ""
    telegram_chat_id: str = ""          # nur diese Chat-ID darf mit dem Coach reden
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Vienna"))
    db_path: Path = ROOT / "data" / "coach.db"

    # LLM
    llm_backend: str = "claude"         # claude | fake
    claude_bin: str = "claude"
    model_cheap: str = "haiku"
    model_smart: str = "sonnet"
    llm_timeout: int = 120
    monthly_budget_usd: float = 20.0
    budget_hard_stop: float = 0.95      # ab diesem Anteil nur noch Vorlagen

    # Check-ins
    checkins: dict[str, str] = field(default_factory=dict)   # "06:30" -> "morgen"
    optional_checkins: set[str] = field(default_factory=set)  # nur bei Bedarf
    followup_minutes: int = 30
    weekly_review: str = "SUN 19:00"

    # Ernährung (Startwerte, per /ziel änderbar)
    kcal_target: int = 2200
    protein_target: int = 150


def load_config(env_file: str | Path | None = None) -> Config:
    if load_dotenv:
        load_dotenv(env_file or ROOT / ".env")
    c = Config()
    c.channel = _env("CHANNEL", "console").lower()
    c.telegram_token = _env("TELEGRAM_BOT_TOKEN")
    c.telegram_chat_id = _env("TELEGRAM_CHAT_ID")
    c.tz = ZoneInfo(_env("TZ_NAME", "Europe/Vienna"))
    if _env("DB_PATH"):
        p = Path(_env("DB_PATH"))
        c.db_path = p if p.is_absolute() else ROOT / p
    c.llm_backend = _env("LLM_BACKEND", "claude").lower()
    c.claude_bin = _env("CLAUDE_BIN", "claude")
    c.model_cheap = _env("MODEL_CHEAP", "haiku")
    c.model_smart = _env("MODEL_SMART", "sonnet")
    c.llm_timeout = int(_env("LLM_TIMEOUT", "120"))
    c.monthly_budget_usd = float(_env("MONTHLY_BUDGET_USD", "20"))
    c.budget_hard_stop = float(_env("BUDGET_HARD_STOP", "0.95"))
    c.checkins = parse_checkins(_env("CHECKINS", DEFAULT_CHECKINS))
    c.optional_checkins = {
        s.strip() for s in _env("OPTIONAL_CHECKINS", "").split(",") if s.strip()
    }
    c.followup_minutes = int(_env("FOLLOWUP_MINUTES", "30"))
    c.weekly_review = _env("WEEKLY_REVIEW", "SUN 19:00").upper()
    c.kcal_target = int(_env("KCAL_TARGET", "2200"))
    c.protein_target = int(_env("PROTEIN_TARGET", "150"))
    return c


def parse_checkins(spec: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        hhmm, _, name = part.partition("=")
        h, m = hhmm.strip().split(":")
        out[f"{int(h):02d}:{int(m):02d}"] = (name or hhmm).strip()
    return out
