"""Project detection plugins (SDD section 10)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

MANIFEST_FILES = [
    "package.json", "Cargo.toml", "go.mod", "requirements.txt",
    "pyproject.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
]

NODE_FRAMEWORKS = [
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("react", "React"), ("vue", "Vue"),
    ("svelte", "Svelte"), ("express", "Express"), ("fastify", "Fastify"),
    ("@nestjs/core", "NestJS"), ("koa", "Koa"),
]


def is_project_root(directory: Path) -> bool:
    if (directory / ".git").exists():
        return True
    return any((directory / f).exists() for f in MANIFEST_FILES)


def _git_info(directory: Path) -> tuple[Optional[str], Optional[str]]:
    if not (directory / ".git").exists():
        return None, None
    remote = branch = None
    try:
        remote = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or None
        branch = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or None
    except Exception:
        pass
    return remote, branch


def _detect_node(directory: Path) -> dict:
    pkg = json.loads((directory / "package.json").read_text())
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    pm = "npm"
    if (directory / "pnpm-lock.yaml").exists():
        pm = "pnpm"
    elif (directory / "yarn.lock").exists():
        pm = "yarn"
    framework = None
    for dep_name, fw in NODE_FRAMEWORKS:
        if dep_name in deps:
            framework = fw
            break
    scripts = pkg.get("scripts", {})
    run_script = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)
    dependencies = [
        {"name": n, "version": v, "is_dev": n in pkg.get("devDependencies", {})}
        for n, v in deps.items()
    ]
    return {
        "name": pkg.get("name") or directory.name,
        "language": "javascript/typescript",
        "framework": framework,
        "package_manager": pm,
        "install_cmd": f"{pm} install",
        "run_cmd": f"{pm} run {run_script}" if run_script else None,
        "build_cmd": f"{pm} run build" if "build" in scripts else None,
        "dependencies": dependencies,
    }


def _detect_python(directory: Path) -> dict:
    deps: list[dict] = []
    framework = None
    pm = "pip"
    req_file = directory / "requirements.txt"
    pyproject = directory / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(errors="ignore")
        if "poetry" in text:
            pm = "poetry"
        for name, fw in [("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI")]:
            if name in text.lower():
                framework = fw
                break
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>~!].*)?$", line)
            if m:
                name = m.group(1)
                deps.append({"name": name, "version": (m.group(2) or "").lstrip("=") or None})
                if framework is None:
                    fw = {"django": "Django", "flask": "Flask", "fastapi": "FastAPI"}.get(name.lower())
                    if fw:
                        framework = fw
    install_cmd = "poetry install" if pm == "poetry" else "pip install -r requirements.txt"
    return {
        "name": directory.name,
        "language": "python",
        "framework": framework,
        "package_manager": pm,
        "install_cmd": install_cmd,
        "run_cmd": None,
        "build_cmd": None,
        "dependencies": deps,
    }


def _detect_rust(directory: Path) -> dict:
    name = directory.name
    deps: list[dict] = []
    text = (directory / "Cargo.toml").read_text(errors="ignore")
    m = re.search(r'name\s*=\s*"([^"]+)"', text)
    if m:
        name = m.group(1)
    in_deps = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_deps = line.startswith("[dependencies")
            continue
        if in_deps and "=" in line:
            dep_name = line.split("=", 1)[0].strip()
            if dep_name:
                deps.append({"name": dep_name, "version": None})
    return {
        "name": name, "language": "rust", "framework": None,
        "package_manager": "cargo", "install_cmd": "cargo build",
        "run_cmd": "cargo run", "build_cmd": "cargo build --release",
        "dependencies": deps,
    }


def _detect_go(directory: Path) -> dict:
    text = (directory / "go.mod").read_text(errors="ignore")
    m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    name = (m.group(1).split("/")[-1] if m else directory.name)
    return {
        "name": name, "language": "go", "framework": None,
        "package_manager": "go", "install_cmd": "go mod download",
        "run_cmd": "go run .", "build_cmd": "go build ./...",
        "dependencies": [],
    }


def _detect_java(directory: Path) -> dict:
    is_gradle = (directory / "build.gradle").exists() or (directory / "build.gradle.kts").exists()
    pm = "gradle" if is_gradle else "maven"
    framework = None
    manifest = directory / ("build.gradle" if is_gradle else "pom.xml")
    if manifest.exists() and "spring-boot" in manifest.read_text(errors="ignore").lower():
        framework = "Spring Boot"
    return {
        "name": directory.name, "language": "java", "framework": framework,
        "package_manager": pm,
        "install_cmd": "gradle build" if is_gradle else "mvn install",
        "run_cmd": "gradle bootRun" if is_gradle else "mvn spring-boot:run",
        "build_cmd": "gradle build" if is_gradle else "mvn package",
        "dependencies": [],
    }


def _detect_docker_only(directory: Path) -> dict:
    return {
        "name": directory.name, "language": "docker", "framework": "Docker Compose",
        "package_manager": None, "install_cmd": None,
        "run_cmd": "docker compose up -d", "build_cmd": "docker compose build",
        "dependencies": [],
    }


def detect_all(directory: Path) -> dict:
    """Run the detector chain (SDD 10) and return normalized ProjectFacts."""
    facts = None
    if (directory / "package.json").exists():
        facts = _detect_node(directory)
    elif (directory / "pyproject.toml").exists() or (directory / "requirements.txt").exists():
        facts = _detect_python(directory)
    elif (directory / "Cargo.toml").exists():
        facts = _detect_rust(directory)
    elif (directory / "go.mod").exists():
        facts = _detect_go(directory)
    elif (directory / "pom.xml").exists() or (directory / "build.gradle").exists() or (directory / "build.gradle.kts").exists():
        facts = _detect_java(directory)
    elif (directory / "docker-compose.yml").exists() or (directory / "docker-compose.yaml").exists():
        facts = _detect_docker_only(directory)
    else:
        facts = {
            "name": directory.name, "language": None, "framework": None,
            "package_manager": None, "install_cmd": None, "run_cmd": None,
            "build_cmd": None, "dependencies": [],
        }

    remote, branch = _git_info(directory)
    facts["path"] = str(directory.resolve())
    facts["git_remote"] = remote
    facts["git_branch"] = branch
    facts["metadata_json"] = json.dumps({})
    return facts
