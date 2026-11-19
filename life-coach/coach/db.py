"""SQLite-Datenbank: Schema + kleine Hilfsfunktionen."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, direction TEXT NOT NULL,
  text TEXT NOT NULL, kind TEXT DEFAULT 'chat');

CREATE TABLE IF NOT EXISTS days (
  date TEXT PRIMARY KEY, wake_time TEXT, sleep_time TEXT,
  mood INTEGER, energy INTEGER,
  one_thing TEXT, one_thing_min TEXT, one_thing_done INTEGER DEFAULT 0,
  went_well TEXT, went_badly TEXT, tomorrow TEXT);

CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, category TEXT, fact TEXT NOT NULL,
  active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, goal TEXT,
  next_step TEXT, deadline TEXT, status TEXT DEFAULT 'aktiv',
  priority INTEGER DEFAULT 0, created TEXT, updated TEXT);

CREATE TABLE IF NOT EXISTS project_log (
  id INTEGER PRIMARY KEY, project_id INTEGER, ts TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY, ts TEXT, category TEXT, text TEXT,
  status TEXT DEFAULT 'vorgeschlagen');

CREATE TABLE IF NOT EXISTS weights (date TEXT PRIMARY KEY, kg REAL);

CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  kcal REAL, protein REAL, carbs REAL, fat REAL, minutes INTEGER,
  slot TEXT DEFAULT 'any', tags TEXT, ingredients TEXT, instructions TEXT,
  source TEXT DEFAULT 'seed', macros_verified INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0, eaten INTEGER DEFAULT 0,
  last_suggested TEXT, created TEXT);

CREATE TABLE IF NOT EXISTS meals (
  id INTEGER PRIMARY KEY, ts TEXT, date TEXT, name TEXT,
  kcal REAL, protein REAL, recipe_id INTEGER);

CREATE TABLE IF NOT EXISTS meal_suggestions (
  id INTEGER PRIMARY KEY, ts TEXT, recipe_id INTEGER, rating TEXT);

CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY, date TEXT, type TEXT, minutes REAL,
  distance_km REAL, handstand_sec REAL, note TEXT);

CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY, ts TEXT, model TEXT, purpose TEXT,
  cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER, ok INTEGER);

CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY, date TEXT, name TEXT, sent_ts TEXT,
  answered INTEGER DEFAULT 0, followed_up INTEGER DEFAULT 0,
  UNIQUE(date, name));
"""


class DB:
    def __init__(self, path: Path | str):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- generische Helfer -------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def x(self, sql: str, args: tuple = ()) -> int:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid

    # --- key/value ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:
        self.x(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # --- Tag ---------------------------------------------------------------
    def day(self, date: str) -> sqlite3.Row:
        self.x("INSERT OR IGNORE INTO days(date) VALUES(?)", (date,))
        return self.one("SELECT * FROM days WHERE date=?", (date,))

    def update_day(self, date: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return
        self.day(date)
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE days SET {cols} WHERE date=?", (*fields.values(), date))
