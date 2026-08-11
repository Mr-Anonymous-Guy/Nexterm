"""Deterministic-first NL intent parser (SDD section 22). No AI model in v0.1 —
tiny-model escalation is a documented extension point (see SDD 18/22)."""
from __future__ import annotations

import re

RULES = [
    (re.compile(r"^clone\s+(.+)$", re.I), "clone"),
    (re.compile(r"^explain\s+(.+)$", re.I), "explain"),
    (re.compile(r"^fix\s+(.+)$", re.I), "fix"),
    (re.compile(r"^ship\s+(.+)$", re.I), "ship"),
    (re.compile(r"^up\s+(.+)$", re.I), "up"),
    (re.compile(r"^down\s+(.+)$", re.I), "down"),
    (re.compile(r"^stack\s+(.+)$", re.I), "stack"),
    (re.compile(r"^ask\s+(.+)$", re.I), "ask"),
    (re.compile(r"^(?:start|run)\s+(.+)$", re.I), "start"),
    (re.compile(r"^open\s+(.+)$", re.I), "open"),
    (re.compile(r"^update\s+every\s+(\w+)\s+project", re.I), "update_every"),
    (re.compile(r"^find\s+projects?\s+using\s+(\S+)\s+(\S+)", re.I), "find_dep_version"),
    (re.compile(r"haven'?t\s+opened\s+in\s+(\d+)\s*months?", re.I), "inactive"),
    (re.compile(r"^find\s+(.+)$", re.I), "find"),
]


def parse_intent(text: str) -> dict | None:
    for pattern, action in RULES:
        m = pattern.match(text.strip())
        if m:
            return {"action": action, "args": m.groups()}
    return None
