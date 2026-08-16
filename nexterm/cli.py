"""worksapce CLI  -- a local developer operating system. Address your projects by name."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import click

from . import db, scanner, search, tags as tags_mod, doctor, service, nlp
from . import repo, process, stack as stack_mod, ship as ship_mod, ai as ai_mod, daemon as daemon_mod
from . import terminal as terminal_mod
from . import errors as errors_mod
from . import release as release_mod
from . import guardian as guardian_mod
from . import __version__


def _conn():
    return db.connect()


_prev_dir: Path | None = None


def _get_prompt(conn) -> str:
    cwd = Path.cwd()
    return f"worksapce {cwd}> "


def _handle_cd(arg: str | None, error_mode: str = "normal"):
    global _prev_dir
    current = Path.cwd()
    if not arg or arg == "~":
        target = Path.home()
    elif arg == "-":
        if _prev_dir:
            target = _prev_dir
        else:
            click.echo("cd: OLDPWD not set")
            return
    else:
        target = Path(arg).expanduser()
        if not target.is_absolute():
            target = (current / target).resolve()

    if target.exists() and target.is_dir():
        _prev_dir = current
        os.chdir(target)
    else:
        # Find similar directories for suggestions
        similar = []
        try:
            parent = target.parent if target.parent.exists() else current
            similar = [
                d.name for d in parent.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ][:10]
        except Exception:
            pass
        click.echo(errors_mod.format_directory_error(
            str(arg), cwd=str(current), similar_dirs=similar,
        ))


def interactive_shell():
    click.echo("============================================================")
    click.echo(f"           worksapce Interactive Shell (v{__version__})")
    click.echo("============================================================")

    conn = _conn()
    devos_commands = set(main.commands.keys()) | {"--help", "-h", "--version", "-V"}

    # Get error display mode from Click context
    try:
        ctx = click.get_current_context()
        error_mode = "normal"
        if ctx.params.get("debug"):
            error_mode = "debug"
        elif ctx.params.get("verbose"):
            error_mode = "verbose"
    except RuntimeError:
        error_mode = "normal"

    try:
        session = terminal_mod.create_prompt_session(_conn)
    except Exception:
        session = None

    while True:
        try:
            prompt = _get_prompt(conn)
            if session:
                line = session.prompt(prompt).strip()
            else:
                line = input(prompt).strip()

            if not line or line.startswith("#"):
                continue

            lower_line = line.lower()
            for prefix in ("nexterm ", "worksapce ", "workspace ", "work ", "developeros "):
                if lower_line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    lower_line = line.lower()
                    break

            if not line:
                continue

            if lower_line in ("exit", "quit", "q"):
                click.echo("Goodbye!")
                break

            if lower_line in ("clear", "cls"):
                os.system("cls" if os.name == "nt" else "clear")
                continue

            if lower_line == "pwd":
                click.echo(os.getcwd())
                continue

            # Support cd, cd.., cd., cd/, cd\, cd~, cd-, cd,, variants
            if lower_line == "cd" or lower_line.startswith("cd ") or (len(lower_line) > 2 and lower_line[:2] == "cd" and not lower_line[2].isalnum()):
                if lower_line == "cd":
                    arg = None
                elif lower_line.startswith("cd "):
                    arg = line[3:].strip()
                else:
                    arg = line[2:].strip()

                if arg:
                    # Normalize comma typos like cd,, to cd..
                    arg = arg.replace(",", ".")
                    if (arg.startswith('"') and arg.endswith('"')) or (arg.startswith("'") and arg.endswith("'")):
                        arg = arg[1:-1]
                _handle_cd(arg, error_mode=error_mode)
                continue

            first_word = line.split()[0].lower()

            if first_word in devos_commands:
                parse_line = line
                if os.name == "nt":
                    parse_line = parse_line.replace("\\", "\\\\")
                args = shlex.split(parse_line)
                try:
                    main.main(args=args, standalone_mode=False)
                except click.ClickException as e:
                    e.show()
                except SystemExit:
                    pass
                except Exception as e:
                    click.echo(errors_mod.format_devos_error(
                        title="Internal command error",
                        message=str(e),
                        command=line,
                    ))
            else:
                # External command execution through the error pipeline
                try:
                    result = errors_mod.run_command(line, cwd=os.getcwd(), capture=False)

                    if result.exit_code is not None and result.exit_code != 0 and not result.was_interrupted:
                        # Non-zero exit: run the structured error pipeline
                        # Re-execute with capture to get stderr for classification
                        captured = errors_mod.run_command(line, cwd=os.getcwd(), capture=True)
                        output = errors_mod.classify_and_format(captured, mode=error_mode)
                        click.echo(output)

                        # Record error in DB
                        try:
                            error_obj = errors_mod.classify_error(captured)
                            db.record_error(
                                conn,
                                command=line,
                                cwd=os.getcwd(),
                                exit_code=captured.exit_code,
                                category=error_obj.category.value,
                                source=error_obj.source.value,
                                title=error_obj.title,
                                summary=error_obj.clean_message,
                            )
                        except Exception:
                            pass  # DB recording must never crash the shell

                    elif result.was_interrupted:
                        click.echo("\nInterrupted.")

                except KeyboardInterrupt:
                    click.echo("\nInterrupted.")
                except Exception as e:
                    # The error handler must NEVER crash the shell
                    click.echo(errors_mod.format_devos_error(
                        title="Command execution error",
                        message=str(e),
                        command=line,
                    ))

        except KeyboardInterrupt:
            click.echo()
            continue
        except EOFError:
            click.echo("\nGoodbye!")
            break


# --- Root Group -------------------------------------------------------
@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="nexterm")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show verbose error output")
@click.option("--debug", is_flag=True, default=False, help="Show full debug diagnostics")
@click.pass_context
def main(ctx, verbose, debug):
    """nexterm  -- a local developer operating system. Address your projects by name."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    if ctx.invoked_subcommand is None:
        interactive_shell()


@main.command("shell")
def shell_cmd():
    """Launch the interactive worksapce command shell."""
    interactive_shell()


# --- Scan -------------------------------------------------------------
@main.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--max-depth", default=4, show_default=True, help="Maximum directory depth to scan")
def scan(paths, max_depth):
    """Index one or more workspace roots."""
    conn = _conn()
    result = scanner.full_scan(conn, [Path(p) for p in paths], max_depth=max_depth)
    click.echo(f"Scanned {result['scanned']} directories, indexed {result['updated']} projects.")


# --- Find / Search ----------------------------------------------------
@main.command()
@click.argument("query", required=False, default=None)
@click.option("--framework", default=None, help="Filter by framework (e.g. Next.js, Django)")
@click.option("--language", default=None, help="Filter by language (e.g. python, javascript)")
@click.option("--dep", default=None, help="Filter by dependency name (e.g. react)")
@click.option("--dep-version", default=None, help="Dependency version prefix (e.g. 19)")
@click.option("--tag", default=None, help="Filter by tag name")
@click.option("--inactive", default=None, type=int, help="Not opened in N days")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def find(query, framework, language, dep, dep_version, tag, inactive, as_json):
    """Search projects by name, framework, language, dependency, tag, or inactivity.

    Run with no arguments to list all indexed projects.
    """
    conn = _conn()
    rows = search.find(
        conn, query=query, framework=framework, language=language,
        dependency=dep, dep_version_prefix=dep_version, tag=tag, inactive_days=inactive,
    )
    _print_projects(rows, as_json)


@main.command("projects")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def projects_cmd(as_json):
    """List all indexed projects."""
    conn = _conn()
    rows = search.find(conn)
    _print_projects(rows, as_json)


@main.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json):
    """Alias for projects: List all indexed projects."""
    conn = _conn()
    rows = search.find(conn)
    _print_projects(rows, as_json)


@main.command("search")
@click.argument("query", required=False, default=None)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def search_cmd(query, as_json):
    """Alias for find: Search projects index."""
    conn = _conn()
    rows = search.find(conn, query=query)
    _print_projects(rows, as_json)


@main.command("register")
@click.argument("path", type=click.Path(exists=True))
def register_cmd(path):
    """Register a workspace directory path."""
    conn = _conn()
    result = scanner.full_scan(conn, [Path(path)])
    click.echo(f"Registered path: {path} (Indexed {result['updated']} projects).")


@main.command("unregister")
@click.argument("name")
def unregister_cmd(name):
    """Unregister a project from index (mark as inactive)."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"No project matching '{name}' found.")
        sys.exit(1)
    p = matches[0]
    db.unregister_project(conn, p["id"])
    click.echo(f"Unregistered project '{p['name']}'.")


@main.command("rescan")
def rescan_cmd():
    """Rescan all indexed workspace roots."""
    conn = _conn()
    roots = db.get_all_roots(conn)
    if not roots:
        click.echo("No registered roots found. Run scan <path> first.")
        return
    res = scanner.full_scan(conn, roots)
    click.echo(f"Rescanned {res['scanned']} directories, updated {res['updated']} projects.")


@main.command("index")
def index_cmd():
    """Alias for rescan: Rebuild/update workspace index."""
    conn = _conn()
    roots = db.get_all_roots(conn)
    if not roots:
        click.echo("No registered roots found. Run scan <path> first.")
        return
    res = scanner.full_scan(conn, roots)
    click.echo(f"Indexed {res['scanned']} directories, updated {res['updated']} projects.")


@main.command("info")
@click.argument("name")
def info_cmd(name):
    """Display detailed project information and metadata."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"No project matching '{name}' found.")
        sys.exit(1)
    p = matches[0]
    info = db.get_project_info(conn, p["id"]) or p
    click.echo(f"Project         : {info['name']}")
    click.echo(f"Path            : {info['path']}")
    click.echo(f"Language        : {info.get('language') or '-'}")
    click.echo(f"Framework       : {info.get('framework') or '-'}")
    click.echo(f"Package Manager : {info.get('package_manager') or '-'}")
    click.echo(f"Install Command : {info.get('install_cmd') or '-'}")
    click.echo(f"Start Command   : {info.get('run_cmd') or '-'}")
    click.echo(f"Build Command   : {info.get('build_cmd') or '-'}")
    click.echo(f"Git Remote      : {info.get('git_remote') or '-'}")
    click.echo(f"Git Branch      : {info.get('git_branch') or '-'}")
    tags_str = ", ".join(info.get("tags", [])) if info.get("tags") else "None"
    click.echo(f"Tags            : {tags_str}")


# --- Open -------------------------------------------------------------
@main.command()
@click.argument("name")
@click.option("--editor", default=None, help="Editor command (default: stored preference or 'code')")
def open(name, editor):
    """Open a project by (fuzzy) name: launches editor and prints how to start it."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"No project matching '{name}' found. Run `worksapce scan <path>` first.")
        sys.exit(1)
    project = matches[0]
    db.touch_last_opened(conn, project["id"])
    db.record_workflow(conn, "open", project["id"], True)

    # Resolve editor from preference or default
    editor = editor or db.get_preference(conn, "editor", "code")
    click.echo(f"Opening {project['name']} ({project['path']})")
    if shutil.which(editor):
        subprocess.Popen([editor, project["path"]])
    else:
        click.echo(f"  (editor '{editor}' not found on PATH  -- skipping editor launch)")
    if project["run_cmd"]:
        click.echo(f"  run: {project['run_cmd']}")


# --- Start (Full Auto-Bootstrap) -------------------------------------
@main.command()
@click.argument("name", required=False, default=None)
@click.option("--no-browser", is_flag=True, help="Skip automatic browser opening")
def start(name, no_browser):
    """Smart-start a project: detect -> install -> env -> services -> run interactively.

    This is the all-in-one bootstrap command (Feature #8).
    The application runs in the current terminal session (foreground).
    Press Ctrl+C to stop it and return to the shell.

    Usage:
        start              Start the project in the current directory
        start <name>       Start an indexed project by name
    """
    from . import detectors

    conn = _conn()
    project_id = None  # May remain None for CWD-based start

    if name:
        # ── Mode 2: Existing project-name lookup ─────────────────────
        matches = search.fuzzy_find(conn, name, limit=1)
        if not matches:
            click.echo(f"No project matching '{name}' found.")
            sys.exit(1)
        project = matches[0]
        project_dir = Path(project["path"])
        project_id = project["id"]
        click.echo(f"Starting '{project['name']}' at {project_dir}")
        facts = detectors.detect_all(project_dir)
        run_cmd = facts.get("run_cmd") or project["run_cmd"]
    else:
        # ── Mode 1: Current working directory ────────────────────────
        project_dir = Path.cwd()
        click.echo(f"Detecting project in {project_dir}...")
        if not detectors.is_project_root(project_dir):
            click.echo(f"  No supported project detected in {project_dir}.")
            click.echo("  Expected one of: package.json, pyproject.toml, Cargo.toml, go.mod, etc.")
            sys.exit(1)
        facts = detectors.detect_all(project_dir)
        run_cmd = facts.get("run_cmd")
        project_name = facts.get("name") or project_dir.name
        click.echo(f"  Detected: {project_name} ({facts.get('language') or 'unknown'})")
        if facts.get("framework"):
            click.echo(f"  Framework: {facts['framework']}")

    # ── Shared Smart Start pipeline ──────────────────────────────────
    pm = facts.get("package_manager")
    install_cmd = facts.get("install_cmd")

    # 1. Check and install dependencies (interactive — output visible in terminal)
    if pm in ("npm", "pnpm", "yarn") and (project_dir / "package.json").exists() and not (project_dir / "node_modules").exists():
        click.echo(f"  Dependencies missing. Installing ({pm})...")
        install_result = subprocess.run(install_cmd, shell=True, cwd=project_dir)
        if install_result.returncode != 0:
            click.echo(f"  Dependency installation failed (exit code {install_result.returncode}).")
            sys.exit(1)
        click.echo(f"  Dependencies installed successfully.")
    elif pm == "pip" and (project_dir / "requirements.txt").exists():
        click.echo("  Installing Python dependencies...")
        install_result = subprocess.run(["pip", "install", "-r", "requirements.txt"], cwd=project_dir)
        if install_result.returncode != 0:
            click.echo(f"  Python dependency installation failed (exit code {install_result.returncode}).")
            sys.exit(1)
        click.echo(f"  Python dependencies installed successfully.")
    else:
        click.echo("  Dependencies already installed.")

    # 2. Generate .env if missing
    if not (project_dir / ".env").exists():
        for template in [".env.example", ".env.template", ".env.sample"]:
            if (project_dir / template).exists():
                shutil.copy(project_dir / template, project_dir / ".env")
                click.echo(f"  Created .env from {template}")
                break

    # 3. Start infrastructure services (docker, db, redis) in background
    stack_services = stack_mod.detect_stack(project_dir)
    infra_services = [s for s in stack_services if s["kind"] != "app"]
    if infra_services:
        for svc in infra_services:
            cmd = svc.get("start_cmd")
            port = svc.get("port")
            if port and stack_mod.is_port_open(port):
                click.echo(f"  Stack: {svc['name']} -> running (port {port} in use)")
                continue
            if cmd:
                if project_id is not None:
                    res = process.start_process(conn, project_id, svc["name"], cmd, project_dir)
                    click.echo(f"  Stack: {svc['name']} -> started (PID: {res['pid']})")
                else:
                    # CWD mode: start infra without DB tracking
                    subprocess.Popen(cmd, shell=True, cwd=project_dir,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    click.echo(f"  Stack: {svc['name']} -> started")
            else:
                click.echo(f"  Stack: {svc['name']} -> no start command configured")

    # 4. Run the application interactively in the current terminal
    if run_cmd:
        # Duplicate process guard: check if the app port is already in use
        framework = facts.get("framework") or ""
        port = 3000 if "Next" in framework or "React" in framework else 8000
        if stack_mod.is_port_open(port):
            click.echo(f"  Port {port} is already in use. Another instance may be running.")
            sys.exit(1)

        # Open browser in background thread (polls until port is ready)
        if not no_browser:
            def _open_browser_when_ready(target_port, timeout=30):
                for _ in range(timeout * 2):
                    if stack_mod.is_port_open(target_port):
                        url = f"http://localhost:{target_port}"
                        click.echo(f"  Opening browser: {url}")
                        webbrowser.open(url)
                        return
                    time.sleep(0.5)
            threading.Thread(
                target=_open_browser_when_ready, args=(port,), daemon=True
            ).start()

        click.echo(f"  Running: {run_cmd}")
        try:
            subprocess.run(run_cmd, shell=True, cwd=project_dir)
        except KeyboardInterrupt:
            click.echo("\n  Stopped.")
    else:
        click.echo("  No run command detected for this project.")

    # Record workflow in DB (only when project is indexed)
    if project_id is not None:
        db.touch_last_opened(conn, project_id)
        db.record_workflow(conn, "start", project_id, True)


# --- Clone ------------------------------------------------------------
@main.command()
@click.argument("repo_url")
def clone(repo_url):
    """Clone a repository and perform automated workspace bootstrap."""
    conn = _conn()
    try:
        res = repo.clone_repository(conn, repo_url)
        click.echo(f"Successfully bootstrapped project '{res['name']}' at {res['path']}")
        for act in res["actions"]:
            click.echo(f"  [OK] {act}")
    except Exception as e:
        click.echo(errors_mod.format_devos_error(
            title="Clone failed",
            message=str(e),
            command=f"clone {repo_url}",
            suggestions=["Check the repository URL.", "Ensure you have network access and Git credentials."],
        ))
        sys.exit(1)


# --- Tags -------------------------------------------------------------
@main.group()
def tag():
    """Add, remove, or list tags on a project."""


@tag.command("add")
@click.argument("name")
@click.argument("tag_name")
def tag_add(name, tag_name):
    """Add a tag to a project. Example: worksapce tag add portfolio frontend"""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo("No matching project.")
        sys.exit(1)
    tags_mod.add_tag(conn, matches[0]["id"], tag_name)
    click.echo(f"Tagged {matches[0]['name']} with '{tag_name}'")


@tag.command("rm")
@click.argument("name")
@click.argument("tag_name")
def tag_rm(name, tag_name):
    """Remove a tag from a project."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo("No matching project.")
        sys.exit(1)
    tags_mod.remove_tag(conn, matches[0]["id"], tag_name)
    click.echo(f"Removed tag '{tag_name}' from {matches[0]['name']}")


@tag.command("list")
@click.argument("name")
def tag_list(name):
    """List all tags on a project."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo("No matching project.")
        sys.exit(1)
    project_tags = tags_mod.list_tags(conn, matches[0]["id"])
    if project_tags:
        click.echo(f"Tags for {matches[0]['name']}: {', '.join(project_tags)}")
    else:
        click.echo(f"{matches[0]['name']} has no tags.")


# --- Doctor -----------------------------------------------------------
@main.command("doctor")
@click.option("--fix", is_flag=True, help="Apply repairable findings after confirmation")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def doctor_cmd(fix, as_json):
    """Run diagnostics across toolchains, projects, and ports (Feature #14)."""
    conn = _conn()
    findings = doctor.run_all(conn)
    if as_json:
        click.echo(json.dumps(findings, indent=2))
        return
    try:
        "[OK]".encode(sys.stdout.encoding or "ascii")
        icon_map = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]"}
    except (UnicodeEncodeError, TypeError):
        icon_map = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]"}

    for f in findings:
        icon = icon_map.get(f["severity"], "?")
        click.echo(f"  {icon}  {f['message']}")
    repairable = [f for f in findings if f.get("repairable")]
    if fix and repairable:
        for f in repairable:
            if click.confirm(f"Apply fix for: {f['message']}?"):
                click.echo("  " + doctor.apply_fix(conn, f))
    elif repairable:
        click.echo(f"\n{len(repairable)} finding(s) are repairable  -- rerun with --fix")


# --- Natural Language -------------------------------------------------
@main.command("nl")
@click.argument("text")
def nl_cmd(text):
    """Free-text entrypoint: `worksapce nl "start portfolio"`."""
    intent = nlp.parse_intent(text)
    if not intent:
        click.echo("Couldn't parse that. Try: start <name>, open <name>, find <query>.")
        return
    conn = _conn()
    action, args = intent["action"], intent["args"]
    dispatch = {
        "clone": ["clone"], "explain": ["explain"], "fix": ["fix"],
        "ship": ["ship"], "up": ["up"], "down": ["down"],
        "ask": ["ask"], "start": ["start"], "open": ["open"], "find": ["find"],
    }
    if action in dispatch:
        return main.main(dispatch[action] + [args[0]], standalone_mode=False)
    if action == "stack":
        return main.main(["stack", "status", args[0]], standalone_mode=False)
    if action == "find_dep_version":
        return main.main(["find", "--dep", args[0], "--dep-version", args[1]], standalone_mode=False)
    if action == "inactive":
        return main.main(["find", "--inactive", str(int(args[0]) * 30)], standalone_mode=False)
    click.echo(f"Recognized intent '{action}'  -- not yet wired to an action.")


# --- Up / Down / Logs (Multi-Terminal) --------------------------------
@main.command("up")
@click.argument("name")
def up_cmd(name):
    """Start background multi-terminal processes for a project (Feature #13)."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    p = matches[0]
    run_cmd = p["run_cmd"]
    if not run_cmd:
        click.echo(f"Project '{p['name']}' has no run command detected. Configure one or use `worksapce start`.")
        sys.exit(1)
    res = process.start_process(conn, p["id"], f"{p['name']}-app", run_cmd, Path(p["path"]))
    click.echo(f"Started process '{res['name']}' (PID: {res['pid']}). Logs: {res['log_file']}")


@main.command("down")
@click.argument("name_or_pid")
def down_cmd(name_or_pid):
    """Stop running background processes by name or PID."""
    conn = _conn()
    success = process.stop_process(conn, name_or_pid)
    if success:
        click.echo(f"Stopped process '{name_or_pid}'.")
    else:
        click.echo(f"No running process found for '{name_or_pid}'.")


@main.command("logs")
@click.argument("name_or_pid")
@click.option("--tail", default=50, help="Number of log lines to show")
def logs_cmd(name_or_pid, tail):
    """Show recent log output for a background process."""
    conn = _conn()
    output = process.get_logs(conn, name_or_pid, tail_lines=tail)
    click.echo(output)


# --- Stack ------------------------------------------------------------
@main.group("stack")
def stack_group():
    """Manage service infrastructure stacks: Postgres, Redis, Docker, AI (Feature #36)."""


@stack_group.command("start")
@click.argument("name")
def stack_start(name):
    """Start all detected services for a project in dependency order."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    results = stack_mod.start_stack(conn, matches[0]["id"])
    for r in results:
        click.echo(f"  {r['service']}: {r['status']} (port {r.get('port')})")


@stack_group.command("stop")
@click.argument("name")
def stack_stop(name):
    """Stop all running stack services for a project."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    # Stop all processes linked to the project
    procs = process.list_processes(conn, matches[0]["id"])
    stopped = 0
    for pr in procs:
        if pr["status"] == "running":
            process.stop_process(conn, pr["pid"])
            stopped += 1
            click.echo(f"  Stopped {pr['name']} (PID: {pr['pid']})")
    if stopped == 0:
        click.echo("  No running stack processes found.")


@stack_group.command("status")
@click.argument("name")
def stack_status_cmd(name):
    """Show the status of all stack services for a project."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    results = stack_mod.stack_status(conn, matches[0]["id"])
    for r in results:
        click.echo(f"  {r['name']} ({r['kind']}): {r['status']} (port {r.get('port')})")


@stack_group.command("up")
@click.argument("name")
def stack_up(name):
    """Alias for stack start."""
    return stack_start(name)


@stack_group.command("down")
@click.argument("name")
def stack_down(name):
    """Alias for stack stop."""
    return stack_stop(name)


@stack_group.command("restart")
@click.argument("name")
def stack_restart(name):
    """Restart all stack services for a project."""
    stack_stop(name)
    stack_start(name)


@stack_group.command("logs")
@click.argument("name")
@click.option("--tail", default=50, help="Number of log lines to show")
def stack_logs(name, tail):
    """Show service logs for a project's stack."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    procs = process.list_processes(conn, matches[0]["id"])
    if not procs:
        click.echo("No active stack processes logged.")
        return
    for pr in procs:
        click.echo(f"=== Process Log: {pr['name']} (PID {pr['pid']}) ===")
        out = process.get_logs(conn, pr["pid"], tail_lines=tail)
        click.echo(out)


# --- Ship -------------------------------------------------------------
@main.command("ship")
@click.argument("name")
@click.option("--target", default="production", help="Deployment target environment")
@click.option("--skip-tests", is_flag=True, help="Skip test phase")
def ship_cmd(name, target, skip_tests):
    """Build, test, verify, and validate deployment for a project (Feature #37)."""
    conn = _conn()
    matches = search.fuzzy_find(conn, name, limit=1)
    if not matches:
        click.echo(f"Project '{name}' not found.")
        sys.exit(1)
    res = ship_mod.ship_project(conn, matches[0]["id"], skip_tests=skip_tests, target=target)
    click.echo(f"Ship verification for '{res['project']}': {'SUCCESS' if res['success'] else 'FAILED'}")
    for p in res["phases"]:
        icon = "[OK]" if p["success"] else "[ERR]"
        click.echo(f"  {icon} {p['phase']}: {p['output']}")


# --- AI ---------------------------------------------------------------
@main.group("ai")
def ai_group():
    """Built-in AI Assistant & Model Management (Features #23-35)."""


@ai_group.command("install")
@click.option("--model", default=None, help="Model name to register")
def ai_install(model):
    """Profile hardware and register compatible AI model."""
    conn = _conn()
    prof = ai_mod.profile_hardware()
    click.echo(f"Hardware Profile: RAM {prof['ram_gb']}GB | CPU Cores: {prof['cpu_cores']} | Disk Free: {prof['disk_free_gb']}GB | GPU: {prof.get('gpu') or 'None detected'}")
    click.echo(f"Recommendation: {prof['recommended_model']}")
    model_name = model or "default-local-model"
    res = ai_mod.register_ai_model(conn, model_name, "ollama/gguf", model_name)
    click.echo(f"Registered model '{res['name']}' as active AI runtime.")


@ai_group.command("list")
def ai_list():
    """List all registered AI models."""
    conn = _conn()
    models = ai_mod.list_ai_models(conn)
    if not models:
        click.echo("No AI models registered. Run `worksapce ai install` first.")
        return
    for m in models:
        default_mark = " (default)" if m["is_default"] else ""
        click.echo(f"  {m['name']} [{m['provider']}]{default_mark}")


@ai_group.command("remove")
@click.argument("model_name")
def ai_remove(model_name):
    """Remove a registered AI model."""
    conn = _conn()
    removed = ai_mod.remove_ai_model(conn, model_name)
    if removed:
        click.echo(f"Removed model '{model_name}'.")
    else:
        click.echo(f"Model '{model_name}' not found.")


@main.command()
@click.argument("question")
@click.option("--project", default=None, help="Scope AI response to a specific project")
def ask(question, project):
    """Ask AI assistant about project architecture, bugs, or workflows (Feature #24)."""
    conn = _conn()
    project_id = None
    if project:
        matches = search.fuzzy_find(conn, project, limit=1)
        if matches:
            project_id = matches[0]["id"]
    ans = ai_mod.ask_ai(conn, question, project_id=project_id)
    click.echo(f"\nAI Assistant Response:\n{ans}")


@main.command()
@click.argument("name")
def explain(name):
    """Structured architectural breakdown of a project (Feature #25)."""
    conn = _conn()
    exp = ai_mod.explain_project(conn, name)
    click.echo(json.dumps(exp, indent=2))


@main.command()
@click.argument("name")
def fix(name):
    """Autonomous AI Fix Agent: Inspects, diagnoses, and repairs project issues (Feature #34)."""
    conn = _conn()
    res = ai_mod.fix_project(conn, name)
    click.echo(f"Autonomous Fix Agent for '{res['project']}':")
    click.echo(f"  Issues Analyzed: {res['issues_found']}")
    for rep in res["repairs_applied"]:
        click.echo(f"  [OK] {rep}")


# --- Repo -------------------------------------------------------------
@main.group("repo")
def repo_group():
    """Git repository management across your workspace."""


@repo_group.command("status")
@click.argument("name", required=False, default=None)
def repo_status_cmd(name):
    """Show git status across all indexed repositories (Feature #2)."""
    conn = _conn()
    results = repo.repo_status(conn, name)
    if not results:
        click.echo("No git repositories found.")
        return
    for r in results:
        changes_str = f" ({r['changes']} changes)" if r['changes'] > 0 else ""
        click.echo(f"  {r['name']:<24} {r['branch']}{changes_str}")


# --- Preferences (Personal Memory) -----------------------------------
@main.group("pref")
def pref_group():
    """Manage personal preferences: editor, package manager, etc. (Feature #33)."""


@pref_group.command("set")
@click.argument("key")
@click.argument("value")
def pref_set(key, value):
    """Set a preference. Example: worksapce pref set editor code"""
    conn = _conn()
    db.set_preference(conn, key, value)
    click.echo(f"Preference '{key}' = '{value}'")


@pref_group.command("get")
@click.argument("key")
def pref_get(key):
    """Get a stored preference value."""
    conn = _conn()
    val = db.get_preference(conn, key)
    if val:
        click.echo(f"{key} = {val}")
    else:
        click.echo(f"No preference set for '{key}'.")


@pref_group.command("list")
def pref_list():
    """List all stored preferences."""
    conn = _conn()
    prefs = db.list_preferences(conn)
    if not prefs:
        click.echo("No preferences set. Use `worksapce pref set <key> <value>`.")
        return
    for p in prefs:
        click.echo(f"  {p['key']:<20} {p['value']}")


# --- Daemon -----------------------------------------------------------
@main.group("daemon")
def daemon_group():
    """Manage background real-time workspace indexer and watcher (Feature #38)."""


@daemon_group.command("start")
def daemon_start():
    """Start the background workspace indexer daemon."""
    res = daemon_mod.start_daemon()
    click.echo(f"Daemon {res['status']}. PID: {res.get('pid')}")


@daemon_group.command("stop")
def daemon_stop():
    """Stop the running background daemon."""
    res = daemon_mod.stop_daemon()
    click.echo(f"Daemon {res['status']}.")


@daemon_group.command("status")
def daemon_status():
    """Check if the background daemon is running."""
    pid = daemon_mod.is_daemon_running()
    if pid:
        click.echo(f"Daemon is running (PID: {pid}).")
    else:
        click.echo("Daemon is stopped.")


# --- Status Dashboard ------------------------------------------------
@main.command()
def status():
    """Live System Health & Workspace Dashboard (Feature #22/#44)."""
    conn = _conn()
    projects = conn.execute("SELECT COUNT(*) as cnt FROM projects").fetchone()["cnt"]
    all_rows = conn.execute("SELECT id, name, language, framework, path, run_cmd, last_opened FROM projects WHERE is_active = 1").fetchall()
    procs = process.list_processes(conn)
    running_procs = [pr for pr in procs if pr["status"] == "running"]
    daemon_pid = daemon_mod.is_daemon_running()

    # Gather port info
    common_ports = [3000, 3001, 5000, 5173, 8000, 8080, 5432, 6379]
    active_ports = [p for p in common_ports if stack_mod.is_port_open(p)]

    # Doctor quick summary
    findings = doctor.run_all(conn)
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warn"]

    click.echo("============================================================")
    click.echo("             worksapce Live Health Dashboard")
    click.echo("============================================================")
    click.echo(f" Indexed Projects  : {projects}")
    click.echo(f" Active Processes  : {len(running_procs)}")
    click.echo(f" Background Daemon : {'RUNNING (PID ' + str(daemon_pid) + ')' if daemon_pid else 'STOPPED'}")
    click.echo(f" Active Ports      : {', '.join(str(p) for p in active_ports) if active_ports else 'None'}")
    click.echo(f" Health            : {len(errors)} errors, {len(warnings)} warnings")
    click.echo("------------------------------------------------------------")

    if running_procs:
        click.echo(" Running Processes:")
        for pr in running_procs:
            click.echo(f"   PID {pr['pid']:<6} {pr['name']:<20} {pr['command']}")
    else:
        click.echo("  No active background processes.")

    if errors:
        click.echo(" Issues:")
        for e in errors[:5]:
            click.echo(f"   [ERR] {e['message']}")

    click.echo("------------------------------------------------------------")


# --- Errors -----------------------------------------------------------
@main.command("errors")
@click.option("--limit", default=20, help="Number of recent errors to show")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--clear", is_flag=True, help="Clear error history")
def errors_cmd(limit, as_json, clear):
    """Show recent command error history."""
    conn = _conn()
    if clear:
        conn.execute("DELETE FROM error_history")
        conn.commit()
        click.echo("Error history cleared.")
        return

    recent = db.get_recent_errors(conn, limit=limit)
    if as_json:
        click.echo(json.dumps(recent, indent=2))
        return
    if not recent:
        click.echo("No recent errors recorded.")
        return

    click.echo(f"  {'TIME':<22} {'EXIT':<6} {'CATEGORY':<24} COMMAND")
    click.echo(f"  {'-'*22} {'-'*6} {'-'*24} {'-'*30}")
    for e in recent:
        ts = e["occurred_at"][:19].replace("T", " ") if e["occurred_at"] else "-"
        exit_code = str(e["exit_code"]) if e["exit_code"] is not None else "-"
        click.echo(f"  {ts:<22} {exit_code:<6} {e['category']:<24} {e['command'][:40]}")


# --- Release Management ------------------------------------------------
@main.group("release")
def release_group():
    """Package & Release Management Subsystem (Feature #45)."""


@release_group.command("check")
@click.option("--tag", default=None, help="Validate against a target Git release tag (e.g. v0.1.0)")
def release_check_cmd(tag):
    """Run complete pre-release validation suite (git status, version, tests, build, metadata, secrets)."""
    validator = release_mod.ReleaseValidator()
    report = validator.run_full_check(target_tag=tag)
    click.echo(release_mod.format_report_terminal(report))
    if not report.all_passed:
        sys.exit(1)


@release_group.command("build")
def release_build_cmd():
    """Build sdist and wheel packages into dist/."""
    validator = release_mod.ReleaseValidator()
    check, files = validator.build_packages()
    click.echo(f"Build result: {'[OK]' if check.passed else '[ERR]'} {check.message}")
    if not check.passed:
        sys.exit(1)


@release_group.command("verify")
def release_verify_cmd():
    """Verify built artifacts with twine check, artifact secret scan, and clean venv smoke test."""
    validator = release_mod.ReleaseValidator()
    meta_check = validator.validate_metadata()
    secret_check = validator.scan_artifact_secrets()
    venv_check = validator.clean_environment_smoke_test()

    for c in [meta_check, secret_check, venv_check]:
        status = "[OK]" if c.passed else "[ERR]"
        click.echo(f"  {status} {c.name:<24} {c.message}")

    if not (meta_check.passed and secret_check.passed and venv_check.passed):
        sys.exit(1)


@release_group.command("status")
def release_status_cmd():
    """Show release readiness status."""
    return release_check_cmd(tag=None)


# --- Manual Pre-Push Check -------------------------------------------
@main.command("check")
@click.option("--verbose", "-v", "check_verbose", is_flag=True, help="Show expanded stage output")
def check_cmd(check_verbose):
    """Run the full pre-push Guardian validation pipeline manually.

    Executes the same 16-stage validation that `git push` triggers,
    with real-time stage-by-stage output. Use this to verify push-safety
    before actually pushing.

    Usage:
        nexterm check           Run all 16 Guardian stages
        nexterm check --verbose Show expanded output per stage
        check                   (inside the interactive shell)
    """
    import time as _time
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.pre_push import (
        PrePushValidationEngine,
        StageResult,
        PrePushReport,
        write_markdown_report,
    )

    # Ensure UTF-8 output on Windows (same pattern as pre_push.py)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    repo_root = Path.cwd()
    sep = "=" * 59

    # --- Detect branch and commit ---
    branch = "unknown"
    commit = "unknown"
    try:
        res_b = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root, capture_output=True, text=True,
            encoding="utf-8", errors="ignore",
        )
        if res_b.returncode == 0:
            branch = res_b.stdout.strip()
        res_c = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, capture_output=True, text=True,
            encoding="utf-8", errors="ignore",
        )
        if res_c.returncode == 0:
            commit = res_c.stdout.strip()
    except Exception:
        pass

    # --- Header ---
    click.echo(sep)
    click.echo("             NEXTERM REPOSITORY GUARDIAN")
    click.echo(sep)
    click.echo()
    click.echo(f"  Repository : {repo_root}")
    click.echo(f"  Branch     : {branch}")
    click.echo(f"  Commit     : {commit}")
    click.echo()

    # --- Initialize engine ---
    engine = PrePushValidationEngine(repo_root, auto_repair=False)

    # Stage definitions (identical to run_full_pipeline)
    stage_funcs = [
        (1, "Repository Audit", engine._stage1_repo_audit),
        (2, "Dependency Verification", engine._stage2_dep_verification),
        (3, "Formatting Check", engine._stage3_formatting_check),
        (4, "Linting Check", engine._stage4_linting_check),
        (5, "Type Check & Static Analysis", engine._stage5_type_check),
        (6, "Production Build", engine._stage6_production_build),
        (7, "Test Suite", engine._stage7_test_suite),
        (8, "GitHub Actions Parsing", engine._stage8_workflow_parsing),
        (9, "Workflow Simulation", engine._stage9_workflow_simulation),
        (10, "Matrix Validation", engine._stage10_matrix_validation),
        (11, "Failure Investigation", engine._stage11_failure_investigation),
        (12, "Auto-Repair Engine", engine._stage12_auto_repair),
        (13, "Security & Secret Scan", engine._stage13_security_secret_scan),
        (14, "Artifact Inspection", engine._stage14_artifact_inspection),
        (15, "Git Conflict & Hygiene", engine._stage15_git_validation),
    ]

    total_stages = len(stage_funcs) + 1  # +1 for Final Decision
    critical_stages = {1, 2, 4, 6, 7, 13}
    completed_stages: list[StageResult] = []
    short_circuited = False
    start_all = _time.time()

    # --- Run stages with real-time output ---
    for s_num, s_name, s_fn in stage_funcs:
        if short_circuited:
            # Mark remaining stages as skipped
            skipped = StageResult(s_num, s_name, False, True, 0.0, "Skipped due to earlier critical failure.")
            completed_stages.append(skipped)
            click.echo(f"  [{s_num:02d}/{total_stages}] {s_name:<29} ○ SKIP")
            click.echo(f"           Skipped due to earlier critical failure.")
            click.echo()
            continue

        click.echo(f"  [{s_num:02d}/{total_stages}] {s_name}")
        click.echo(f"           → checking...")

        result = engine._run_stage(s_num, s_name, s_fn)
        completed_stages.append(result)

        if result.passed:
            click.echo(f"           ✓ PASS   {result.duration:>5.2f}s")
        elif result.skipped:
            click.echo(f"           ○ SKIP   {result.duration:>5.2f}s")
        else:
            click.echo(f"           ✗ FAIL   {result.duration:>5.2f}s")
            click.echo()
            if result.message:
                click.echo(f"           Problem:")
                click.echo(f"           {result.message}")
            if result.details:
                click.echo(f"           Details:")
                for d in result.details[:10]:
                    click.echo(f"             {d}")
            if result.remedy:
                click.echo(f"           Remedy:")
                click.echo(f"             {result.remedy}")

            if s_num in critical_stages:
                short_circuited = True

        if check_verbose and result.details and result.passed:
            for d in result.details[:5]:
                click.echo(f"           {d}")

        click.echo()

    # --- Stage 16: Final Decision ---
    s_num = 16
    s_name = "Final Decision & Report"
    click.echo(f"  [{s_num:02d}/{total_stages}] {s_name}")
    click.echo(f"           → evaluating results...")

    final_result = engine._run_stage(s_num, s_name, lambda: engine._stage16_final_decision(completed_stages))
    completed_stages.append(final_result)

    if final_result.passed:
        click.echo(f"           ✓ PASS   {final_result.duration:>5.2f}s")
    else:
        click.echo(f"           ✗ FAIL   {final_result.duration:>5.2f}s")
        if final_result.message:
            click.echo(f"           {final_result.message}")

    click.echo()

    # --- Build report ---
    total_duration = _time.time() - start_all
    from nexterm import __version__ as _ver
    report = PrePushReport(
        version=_ver,
        branch=branch,
        commit=commit,
        total_duration=total_duration,
    )
    report.stages = completed_stages

    # Write markdown report
    report_path = repo_root / "pre_push_report.md"
    write_markdown_report(report, report_path)

    # --- Summary ---
    passed_count = sum(1 for s in completed_stages if s.passed)
    failed_count = sum(1 for s in completed_stages if not s.passed and not s.skipped)
    skipped_count = sum(1 for s in completed_stages if s.skipped)
    failed_stages = [s for s in completed_stages if not s.passed and not s.skipped]

    click.echo(sep)
    click.echo("             GUARDIAN SUMMARY")
    click.echo(sep)
    click.echo()
    click.echo(f"  ✓ Passed  : {passed_count}")
    click.echo(f"  ✗ Failed  : {failed_count}")
    click.echo(f"  ○ Skipped : {skipped_count}")
    click.echo(f"  Duration  : {total_duration:.2f}s")
    click.echo()

    if report.all_passed:
        click.echo("  PUSH SAFETY: READY")
    else:
        click.echo("  PUSH SAFETY: BLOCKED")
        click.echo()
        if failed_stages:
            click.echo("  Failed stages:")
            for fs in failed_stages:
                click.echo(f"    • {fs.name}")

    click.echo()
    click.echo(f"  Report:")
    click.echo(f"    {report_path}")
    click.echo()
    click.echo(sep)

    if not report.all_passed:
        sys.exit(1)


# --- Pre-Push Guardian ------------------------------------------------
@main.group("guardian")
def guardian_group():
    """Pre-Push Guardian Repository Defense Subsystem."""


@guardian_group.command("check")
def guardian_check_cmd():
    """Run full pre-push Guardian verification pipeline."""
    engine = guardian_mod.GuardianEngine()
    report = engine.run_full_guardian_check()
    click.echo(guardian_mod.format_guardian_report_terminal(report))
    if not report.all_passed:
        sys.exit(1)


@guardian_group.command("run")
def guardian_run_cmd():
    """Run full pre-push Guardian verification pipeline."""
    engine = guardian_mod.GuardianEngine()
    report = engine.run_full_guardian_check()
    click.echo(guardian_mod.format_guardian_report_terminal(report))
    if not report.all_passed:
        sys.exit(1)


@guardian_group.command("pre-push")
def guardian_pre_push_cmd():
    """Alias for guardian check."""
    return guardian_check_cmd()


@guardian_group.command("report")
def guardian_report_cmd():
    """Show the latest Guardian verification report."""
    return guardian_check_cmd()


@guardian_group.command("install-hook")
def guardian_install_hook_cmd():
    """Install DeveloperOS Pre-Push Guardian Git hook (.git/hooks/pre-push)."""
    engine = guardian_mod.GuardianEngine()
    res = engine.install_git_hook()
    click.echo(f"  {'[OK]' if res.passed else '[ERR]'} {res.message}")
    if not res.passed:
        sys.exit(1)


@guardian_group.command("remove-hook")
def guardian_remove_hook_cmd():
    """Remove DeveloperOS Pre-Push Guardian Git hook."""
    engine = guardian_mod.GuardianEngine()
    res = engine.remove_git_hook()
    click.echo(f"  {'[OK]' if res.passed else '[ERR]'} {res.message}")
    if not res.passed:
        sys.exit(1)


@guardian_group.command("status")
def guardian_status_cmd():
    """Check DeveloperOS Pre-Push Guardian hook status."""
    engine = guardian_mod.GuardianEngine()
    is_installed = engine.check_hook_status()
    status_str = "[ACTIVE]" if is_installed else "[NOT INSTALLED]"
    click.echo(f"  Guardian Pre-Push Hook Status: {status_str}")
    click.echo("  Use `workspace guardian install-hook` or `workspace guardian remove-hook` to manage.")




# --- Helpers ----------------------------------------------------------
def _print_projects(rows, as_json: bool):
    if as_json:
        click.echo(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        click.echo("No projects found.")
        return
    click.echo(f"  {'NAME':<24} {'LANGUAGE':<14} {'FRAMEWORK':<12} PATH")
    click.echo(f"  {'-'*24} {'-'*14} {'-'*12} {'-'*30}")
    for r in rows:
        click.echo(f"  {r['name']:<24} {r['language'] or '-':<14} {r['framework'] or '-':<12} {r['path']}")


if __name__ == "__main__":
    main()
