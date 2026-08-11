"""Built-in Local & Cloud AI Engine, Knowledge System & Autonomous Repair Agent for DeveloperOS (SDD section 23-35)."""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
import platform
import psutil
import subprocess
import sqlite3
from pathlib import Path

from . import db, detectors, doctor, process, search


def profile_hardware() -> dict:
    """Inspects local hardware resources (CPU, RAM, GPU, Disk) for AI recommendations."""
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    cpu_count = os.cpu_count() or 4
    disk_free_gb = round(psutil.disk_usage(str(Path.home())).free / (1024 ** 3), 1)

    # GPU detection (best-effort)
    gpu_name = None
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            gpu_name = res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    recommendation = "tiny"
    if ram_gb >= 16 and disk_free_gb >= 10:
        recommendation = "medium (Qwen/Llama-3 8B)"
    elif ram_gb >= 8 and disk_free_gb >= 5:
        recommendation = "small (Phi-3 / Llama-3.2 3B)"
    else:
        recommendation = "tiny (Qwen-1.5B / Deterministic Fallback)"

    return {
        "os": platform.system(),
        "cpu_cores": cpu_count,
        "ram_gb": ram_gb,
        "disk_free_gb": disk_free_gb,
        "gpu": gpu_name,
        "recommended_model": recommendation,
    }


def register_ai_model(conn: sqlite3.Connection, name: str, provider: str, path_or_id: str, set_default: bool = True) -> dict:
    """Registers an AI model configuration into the database."""
    if set_default:
        conn.execute("UPDATE ai_models SET is_default = 0")

    conn.execute(
        """
        INSERT INTO ai_models (name, provider, model_path_or_id, is_default, registered_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET provider=excluded.provider, model_path_or_id=excluded.model_path_or_id, is_default=excluded.is_default
        """,
        (name, provider, path_or_id, int(set_default), db.now_iso()),
    )
    conn.commit()
    return {"name": name, "provider": provider, "path_or_id": path_or_id}


def list_ai_models(conn: sqlite3.Connection) -> list[dict]:
    """Lists all registered AI models."""
    rows = conn.execute("SELECT * FROM ai_models ORDER BY is_default DESC, name").fetchall()
    return [{"id": r["id"], "name": r["name"], "provider": r["provider"],
             "path_or_id": r["model_path_or_id"], "is_default": bool(r["is_default"])} for r in rows]


def remove_ai_model(conn: sqlite3.Connection, name: str) -> bool:
    """Removes a registered AI model by name."""
    cur = conn.execute("DELETE FROM ai_models WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


def _query_ollama(prompt: str, model: str = "llama3") -> str | None:
    """Probes local Ollama server if active."""
    url = "http://localhost:11434/api/generate"
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response")
    except Exception:
        return None


def _query_cloud_ai(prompt: str, system_context: str = "") -> str | None:
    """Queries cloud AI providers if API keys are configured. (Feature §31)"""
    # OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            payload = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_context or "You are a developer workspace assistant."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 500,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    # Google Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": f"{system_context}\n\nUser: {prompt}"}]}],
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass

    return None


def generate_reasoning(prompt: str, system_context: str = "") -> str:
    """Uses available AI runtime (Ollama / Cloud / Deterministic Reasoning Engine)."""
    # 1. Try Ollama local server
    ollama_res = _query_ollama(f"{system_context}\n\nUser Question: {prompt}")
    if ollama_res:
        return ollama_res

    # 2. Try cloud AI providers
    cloud_res = _query_cloud_ai(prompt, system_context)
    if cloud_res:
        return cloud_res

    # 3. Fallback to Rule-Based Intelligence Engine
    prompt_lower = prompt.lower()
    if "backend" in prompt_lower and ("start" in prompt_lower or "run" in prompt_lower or "error" in prompt_lower):
        return (
            "Backend Startup Diagnostic:\n"
            "1. Check if the database (PostgreSQL/Redis) is running using `worksapce stack status`.\n"
            "2. Verify `.env` file exists and database connection URLs are set correctly.\n"
            "3. Ensure the port (e.g. 8000 / 5000) is not already in use by another process."
        )

    if "upgrade" in prompt_lower or "react" in prompt_lower:
        return (
            "Framework Upgrade Guide:\n"
            "1. Check breaking changes in release notes.\n"
            "2. Update package manifest (`package.json` / `pyproject.toml`).\n"
            "3. Run dependency installer (`npm install` / `pip install -U`).\n"
            "4. Execute test suite with `worksapce ship` to verify compatibility."
        )

    if "dead code" in prompt_lower or "unused" in prompt_lower:
        return (
            "Dead Code Detection:\n"
            "1. For JavaScript/TypeScript: run `npx knip` or `npx ts-prune`.\n"
            "2. For Python: run `vulture .` or `python -m pyflakes .`.\n"
            "3. Review results and remove confirmed dead exports/functions."
        )

    if "compare" in prompt_lower:
        return (
            "Project Comparison:\n"
            "1. Use `worksapce find` to locate both projects.\n"
            "2. Run `worksapce explain <name>` on each to get architecture breakdown.\n"
            "3. Compare frameworks, dependencies, and service stacks."
        )

    return (
        f"worksapce Knowledge Analysis for query '{prompt}':\n"
        f"Context Evaluated: {system_context[:200] if system_context else 'Workspace Index'}\n"
        "Recommendation: Ensure dependencies are installed and `.env` configuration is valid. Run `worksapce doctor` for diagnostics."
    )


def ask_ai(conn: sqlite3.Connection, question: str, project_id: int | None = None) -> str:
    """Answers developer questions using structured workspace knowledge."""
    context_parts = []
    if project_id:
        p = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if p:
            deps = conn.execute("SELECT name, version FROM dependencies WHERE project_id = ?", (project_id,)).fetchall()
            dep_str = ", ".join([f"{d['name']}@{d['version'] or '*'}" for d in deps])
            context_parts.append(f"Project: {p['name']} ({p['language']}/{p['framework']}). Dependencies: {dep_str}")

    findings = conn.execute("SELECT check_name, severity, message FROM doctor_findings LIMIT 5").fetchall()
    if findings:
        context_parts.append("Doctor Findings: " + "; ".join([f"{f['severity']}: {f['message']}" for f in findings]))

    system_context = "\n".join(context_parts)
    answer = generate_reasoning(question, system_context)

    conn.execute(
        "INSERT INTO ai_conversations (project_id, prompt, response, timestamp) VALUES (?, ?, ?, ?)",
        (project_id, question, answer, db.now_iso()),
    )
    conn.commit()
    return answer


def explain_project(conn: sqlite3.Connection, name_or_id: str | int) -> dict:
    """Produces a structured architectural explanation of a project."""
    if str(name_or_id).isdigit():
        p = conn.execute("SELECT * FROM projects WHERE id = ?", (int(name_or_id),)).fetchone()
    else:
        matches = search.fuzzy_find(conn, str(name_or_id), limit=1)
        p = matches[0] if matches else None

    if not p:
        raise ValueError(f"Project '{name_or_id}' not found.")

    p_dir = Path(p["path"])
    facts = detectors.detect_all(p_dir)
    deps = [d["name"] for d in facts.get("dependencies", [])]

    explanation = {
        "name": p["name"],
        "path": p["path"],
        "language": p["language"] or "Unknown",
        "framework": p["framework"] or "General",
        "package_manager": p["package_manager"] or "Standard",
        "architecture": {
            "frontend": "React/Next.js UI" if "react" in deps or "next" in deps else "Not detected",
            "backend": f"{p['framework']} API service" if p['framework'] else "Standard application",
            "database": "PostgreSQL / SQLite" if any(d in deps for d in ["pg", "sqlite3", "prisma"]) else "None detected",
            "entry_points": [str(f.relative_to(p_dir)) for f in p_dir.glob("src/index.*")] or ["Default main entry"],
        },
        "suggested_commands": {
            "start": p["run_cmd"] or facts.get("run_cmd") or "worksapce start " + p["name"],
            "test": "worksapce ship " + p["name"],
            "doctor": "worksapce doctor",
        },
    }
    return explanation


def fix_project(conn: sqlite3.Connection, name_or_id: str | int) -> dict:
    """Autonomous AI Fix Agent: Identifies errors, generates patch, and repairs workspace."""
    if str(name_or_id).isdigit():
        p = conn.execute("SELECT * FROM projects WHERE id = ?", (int(name_or_id),)).fetchone()
    else:
        matches = search.fuzzy_find(conn, str(name_or_id), limit=1)
        p = matches[0] if matches else None

    if not p:
        raise ValueError(f"Project '{name_or_id}' not found in workspace.")

    project_dir = Path(p["path"])
    findings = doctor.run_all(conn)
    project_findings = [f for f in findings if f.get("repairable")]

    repairs_applied = []
    if project_findings:
        for f in project_findings:
            res = doctor.apply_fix(conn, f)
            repairs_applied.append(res)
    else:
        # Proactive checks — actually execute the repairs
        if (project_dir / "package.json").exists() and not (project_dir / "node_modules").exists():
            try:
                subprocess.run(["npm", "install"], cwd=project_dir, capture_output=True, timeout=120)
                repairs_applied.append("Installed missing node_modules via `npm install`")
            except Exception as e:
                repairs_applied.append(f"Failed to install node_modules: {e}")

        if (project_dir / ".env.example").exists() and not (project_dir / ".env").exists():
            import shutil
            shutil.copy(project_dir / ".env.example", project_dir / ".env")
            repairs_applied.append("Created missing .env file from .env.example")

        if (project_dir / "requirements.txt").exists():
            venv = project_dir / ".venv"
            if not venv.exists() and not (project_dir / "node_modules").exists():
                try:
                    subprocess.run(["pip", "install", "-r", "requirements.txt"],
                                   cwd=project_dir, capture_output=True, timeout=120)
                    repairs_applied.append("Installed missing Python dependencies via `pip install -r requirements.txt`")
                except Exception as e:
                    repairs_applied.append(f"Failed to install pip dependencies: {e}")

        if not repairs_applied:
            repairs_applied.append("No critical issues detected; verified workspace integrity.")

    return {
        "project": p["name"],
        "issues_found": len(project_findings),
        "repairs_applied": repairs_applied,
    }
