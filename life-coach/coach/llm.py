"""LLM-Zugang ausschließlich über die offizielle Claude Code CLI (`claude -p`).

Kein API-Key, kein Auslesen von Tokens. Der Aufruf wird so schlank wie möglich
gehalten (eigener System-Prompt, keine Tools, keine MCP-Server, keine
Projekt-Settings, leeres Arbeitsverzeichnis), damit das Agent-SDK-Guthaben
lange reicht. Jeder Aufruf wird mit Kosten in `llm_usage` geloggt.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .db import DB

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any] | None
    text: str
    cost_usd: float = 0.0
    error: str = ""


class BudgetExceeded(Exception):
    pass


class LLM:
    def __init__(self, cfg, db: DB):
        self.cfg = cfg
        self.db = db
        # leeres Verzeichnis -> keine CLAUDE.md, keine Projekt-Settings
        self.workdir = tempfile.mkdtemp(prefix="coach-llm-")

    # ------------------------------------------------------------------ budget
    def month_cost(self, now: datetime | None = None) -> float:
        now = now or datetime.now(self.cfg.tz)
        row = self.db.one(
            "SELECT COALESCE(SUM(cost_usd),0) c FROM llm_usage WHERE ts LIKE ?",
            (now.strftime("%Y-%m") + "%",),
        )
        return float(row["c"])

    def budget_share(self) -> float:
        if self.cfg.monthly_budget_usd <= 0:
            return 0.0
        return self.month_cost() / self.cfg.monthly_budget_usd

    def budget_ok(self) -> bool:
        return self.budget_share() < self.cfg.budget_hard_stop

    # ------------------------------------------------------------------- call
    async def ask(
        self,
        system: str,
        prompt: str,
        schema: dict | None = None,
        smart: bool = False,
        purpose: str = "chat",
    ) -> LLMResult:
        if not self.budget_ok():
            return LLMResult(False, None, "", error="budget")
        model = self.cfg.model_smart if smart else self.cfg.model_cheap
        if self.cfg.llm_backend == "fake":
            res = _fake_response(prompt, schema, purpose)
        else:
            res = await self._claude(system, prompt, schema, model)
        self.db.x(
            "INSERT INTO llm_usage(ts,model,purpose,cost_usd,input_tokens,"
            "output_tokens,ok) VALUES(?,?,?,?,?,?,?)",
            (
                datetime.now(self.cfg.tz).isoformat(timespec="seconds"),
                model, purpose, res.cost_usd,
                getattr(res, "_in", 0), getattr(res, "_out", 0), int(res.ok),
            ),
        )
        return res

    async def _claude(self, system, prompt, schema, model) -> LLMResult:
        args = [
            self.cfg.claude_bin, "-p",
            "--model", model,
            "--output-format", "json",
            "--system-prompt", system,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns", "3",
        ]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workdir,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode()), timeout=self.cfg.llm_timeout
            )
        except (asyncio.TimeoutError, FileNotFoundError) as e:
            log.error("claude-Aufruf fehlgeschlagen: %s", e)
            return LLMResult(False, None, "", error=str(e) or "timeout")

        raw = out.decode(errors="replace").strip()
        try:
            env = json.loads(raw)
        except json.JSONDecodeError:
            log.error("Unerwartete claude-Ausgabe: %s | %s", raw[:300], err[:300])
            return LLMResult(False, None, raw, error="parse")

        cost = float(env.get("total_cost_usd") or env.get("cost_usd") or 0)
        usage = env.get("usage") or {}
        text = env.get("result") or ""
        data = env.get("structured_output")
        if data is None and schema:
            data = extract_json(text)
        res = LLMResult(
            ok=not env.get("is_error") and (data is not None or not schema),
            data=data, text=text, cost_usd=cost,
            error="" if not env.get("is_error") else str(env.get("subtype")),
        )
        res._in = int(usage.get("input_tokens", 0)) + int(
            usage.get("cache_read_input_tokens", 0)
        ) + int(usage.get("cache_creation_input_tokens", 0))
        res._out = int(usage.get("output_tokens", 0))
        return res


def extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- fake backend
def _fake_response(prompt: str, schema: dict | None, purpose: str) -> LLMResult:
    """Deterministische Antworten für Tests/Offline-Betrieb (LLM_BACKEND=fake)."""
    if purpose == "recipe":
        data = {
            "name": "Fake-Skyr-Bowl",
            "minutes": 5, "slot": "any", "tags": ["süß", "schnell"],
            "ingredients": [
                {"item": "skyr", "grams": 300},
                {"item": "haferflocken", "grams": 40},
                {"item": "beeren tk", "grams": 100},
            ],
            "instructions": "Alles in eine Schüssel.",
            "estimated": {"kcal": 420, "protein": 38, "carbs": 55, "fat": 4},
            "pitch": "Schnell, süß und eiweißreich.",
        }
    elif purpose in ("weekly", "profile"):
        data = {"reply": "[fake] Wochenrückblick", "taste_profile": "mag schnell & herzhaft"}
    else:
        last = prompt.strip().splitlines()[-1] if prompt.strip() else ""
        data = {"reply": f"[fake] {last[:80]}", "extract": {}}
    return LLMResult(True, data if schema else None, json.dumps(data), cost_usd=0.0)
