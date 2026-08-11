````md
# NexTerm — Complete Command Specification

> This document is the authoritative command inventory for NexTerm.
>
> NexTerm must function as both:
>
> 1. A real interactive system shell.
> 2. An intelligent developer workspace/project management CLI.
>
> **Important:** Native operating-system commands must continue to work normally. NexTerm must not unnecessarily reimplement commands such as `cd`, `npm`, `git`, `docker`, `python`, etc.

---

# 1. Command Architecture

NexTerm has two command layers:

```text
NexTerm
├── Native Shell Commands
│   ├── pwd
│   ├── ls
│   ├── cd
│   ├── npm
│   ├── node
│   ├── python
│   ├── git
│   ├── docker
│   └── any other installed system command
│
└── NexTerm Commands
    ├── projects
    ├── find
    ├── search
    ├── open
    ├── start
    ├── status
    ├── info
    ├── doctor
    ├── tag
    ├── register
    ├── unregister
    ├── rescan
    ├── index
    ├── stack
    ├── ai
    ├── ask
    ├── explain
    ├── fix
    ├── guardian
    └── release
````

NexTerm-native commands should be clearly distinguishable internally, but the user should not have to manually specify whether a command is native or NexTerm-specific.

---

# 2. Launch Commands

## `nexterm`

Launch the interactive NexTerm shell.

```bash
nexterm
```

Expected:

```text
NexTerm Interactive Shell

nexterm C:\Projects>
```

---

## `nexterm --version`

Display the installed NexTerm version.

```bash
nexterm --version
```

Expected:

```text
NexTerm v0.1.0
```

---

## `nexterm --help`

Display the command help system.

```bash
nexterm --help
```

Must list:

* shell functionality
* workspace commands
* project commands
* diagnostics
* AI
* Guardian
* release commands

---

# 3. Native Shell Commands

NexTerm must allow normal OS commands to execute directly.

## `pwd`

Show the current working directory.

```bash
pwd
```

---

## `ls`

List files and directories.

```bash
ls
```

---

## `dir`

Windows directory listing.

```powershell
dir
```

---

## `cd`

Change directory.

```bash
cd <path>
```

Examples:

```bash
cd portfolio
cd ..
cd .
cd ~
cd C:\Projects\portfolio
```

After changing directory, NexTerm's prompt must update.

Example:

```text
nexterm C:\Projects>

cd portfolio

nexterm C:\Projects\portfolio>
```

---

## `mkdir`

Create a directory.

```bash
mkdir <directory>
```

---

## `rmdir`

Remove a directory according to the underlying operating system.

```bash
rmdir <directory>
```

---

## `clear`

Clear the terminal.

```bash
clear
```

---

## `cls`

Windows-compatible terminal clearing.

```powershell
cls
```

---

## `echo`

Print text.

```bash
echo hello
```

---

## `whoami`

Display the current operating-system user.

```bash
whoami
```

---

## `where`

Find an executable on Windows.

```powershell
where node
where npm
where git
```

---

## `which`

Find an executable on Unix-like systems.

```bash
which node
which python
which git
```

---

## `type`

Inspect/resolve a command where supported by the shell.

```powershell
type npm
```

---

## `exit`

Exit the NexTerm interactive shell.

```bash
exit
```

---

# 4. Native Shell Passthrough

Any installed executable that is not a NexTerm-native command should be passed to the operating system.

Examples:

```bash
node
npm
npx
pnpm
yarn
bun
python
pip
java
javac
mvn
gradle
go
cargo
rustc
git
docker
docker-compose
curl
ssh
make
cmake
ffmpeg
code
```

Example:

```text
nexterm C:\Projects\portfolio> npm install
```

must execute the real:

```text
npm install
```

Do not return:

```text
Unknown NexTerm command
```

for valid system commands.

---

# 5. Node.js Commands

NexTerm must transparently support:

```bash
node --version
npm --version
npm install
npm uninstall <package>
npm update
npm run <script>
npm start
npm test
npm run dev
npm run build
npm run lint
npx <command>
```

Also support:

```bash
pnpm --version
pnpm install
pnpm add <package>
pnpm remove <package>
pnpm dev
pnpm build
pnpm test
```

```bash
yarn --version
yarn install
yarn add <package>
yarn remove <package>
yarn dev
yarn build
yarn test
```

```bash
bun --version
bun install
bun add <package>
bun remove <package>
bun run dev
bun run build
bun test
```

NexTerm must not assume that every package manager exists.

If unavailable, show a clean error.

---

# 6. Python Commands

Support normal Python commands:

```bash
python --version
python -m pip --version
python -m pip install <package>
python -m pip uninstall <package>
python -m pip list
python -m pip freeze
python -m venv .venv
python <script>
```

Also:

```bash
pip --version
pip install <package>
pip uninstall <package>
pip list
pip freeze
pytest
```

---

# 7. Java Commands

Support:

```bash
java --version
javac --version
mvn --version
mvn test
mvn package
mvn clean
mvn clean package
gradle --version
gradle build
gradle test
```

Detect Java projects using:

```text
pom.xml
build.gradle
build.gradle.kts
```

---

# 8. Git Commands

All normal Git commands must work.

```bash
git --version
git status
git add .
git commit
git push
git pull
git fetch
git clone
git branch
git switch
git checkout
git log
git diff
git remote
git tag
git stash
git merge
git rebase
```

NexTerm must preserve Git's normal behavior.

---

# 9. Git Push Integration

The normal:

```bash
git push
```

must integrate with NexTerm Guardian.

Expected architecture:

```text
git push
    ↓
NexTerm pre-push hook
    ↓
Guardian
    ↓
Validation
    ↓
PASS ─────────→ actual Git push
    │
    └── FAIL ─→ Git push blocked
```

The Guardian must never silently bypass a failed check.

---

# 10. Docker Commands

Support normal Docker commands:

```bash
docker --version
docker ps
docker images
docker build
docker run
docker stop
docker start
docker restart
docker logs
docker exec
docker inspect
docker pull
docker push
```

Docker Compose:

```bash
docker compose version
docker compose up
docker compose down
docker compose restart
docker compose logs
docker compose ps
docker compose build
```

NexTerm must report clearly when Docker is not installed/running.

---

# 11. Project Listing

## `nexterm projects`

List all indexed projects.

```bash
nexterm projects
```

Example:

```text
NexTerm Projects

portfolio       React / Vite
invoice         FastAPI / React
weather         Next.js
repo-clone      Python
```

---

## `nexterm list`

Alias for project listing.

```bash
nexterm list
```

---

# 12. Project Discovery

## `nexterm find`

Search indexed projects.

```bash
nexterm find <query>
```

Examples:

```bash
nexterm find portfolio
nexterm find invoice
nexterm find react
nexterm find python
nexterm find docker
```

Searching by technology must return matching projects.

---

# 13. Project Search

## `nexterm search`

Search the project index.

```bash
nexterm search <query>
```

Examples:

```bash
nexterm search react
nexterm search postgres
nexterm search invoice
nexterm search frontend
```

The search engine should support:

* project name
* path
* framework
* language
* package manager
* tags
* services
* dependencies

---

# 14. Open Project

## `nexterm open`

Open or switch to a registered project.

```bash
nexterm open <project>
```

Expected behavior may include:

* resolve project
* change working directory
* open VS Code if configured
* restore project context
* show project information

Example:

```bash
nexterm open portfolio
```

---

# 15. Smart Project Start

## `nexterm start`

Start a project intelligently.

```bash
nexterm start <project>
```

Expected workflow:

```text
Find project
    ↓
Detect framework
    ↓
Detect package manager
    ↓
Check dependencies
    ↓
Check environment
    ↓
Check ports
    ↓
Determine start command
    ↓
Start project
```

Example:

```text
✓ Found portfolio
✓ React + Vite detected
✓ npm detected
✓ Dependencies installed
✓ Port 5173 available

Starting:

npm run dev
```

---

# 16. Project Information

## `nexterm info`

Display detailed project metadata.

```bash
nexterm info <project>
```

Expected information:

```text
Project:
Portfolio

Path:
C:\Projects\portfolio

Language:
TypeScript

Framework:
React + Vite

Package Manager:
npm

Install:
npm install

Start:
npm run dev

Build:
npm run build

Port:
5173

Git:
main

Tags:
frontend, react, portfolio
```

---

# 17. Project Status

## `nexterm status`

Show the status of all projects.

```bash
nexterm status
```

---

## `nexterm status <project>`

Show one project's status.

```bash
nexterm status portfolio
```

Possible statuses:

```text
Running
Stopped
Needs installation
Broken
Port conflict
Dependency warning
Healthy
Unknown
```

---

# 18. Doctor

## `nexterm doctor`

Run workspace diagnostics.

```bash
nexterm doctor
```

---

## `nexterm doctor <project>`

Run diagnostics against a project.

```bash
nexterm doctor portfolio
```

Checks should include where relevant:

```text
Node
npm
pnpm
Python
Java
Git
Docker
Dependencies
Environment variables
Ports
Project structure
Git state
Package manager
Build configuration
```

Example:

```text
NexTerm Doctor

✓ Node 22.23.2
✓ npm 11.6.2
✓ Git
✓ package.json
✓ node_modules

⚠ .env missing
✗ Port 5173 already in use
```

---

# 19. Project Registration

## `nexterm register`

Register a project.

```bash
nexterm register <path>
```

Example:

```bash
nexterm register C:\Projects\portfolio
```

---

# 20. Project Unregistration

## `nexterm unregister`

Remove a project from the NexTerm index.

```bash
nexterm unregister <project>
```

This must NOT delete the actual project directory unless explicitly requested.

---

# 21. Rescan

## `nexterm rescan`

Rescan registered projects.

```bash
nexterm rescan
```

Detect:

* new projects
* changed project types
* changed commands
* changed dependencies
* changed paths

---

# 22. Index

## `nexterm index`

Rebuild or update the local project index.

```bash
nexterm index
```

The index should store structured metadata rather than repeatedly performing expensive full filesystem scans.

---

# 23. Tags

## `nexterm tag`

Assign tags to projects.

```bash
nexterm tag <project> <tag>
```

Example:

```bash
nexterm tag portfolio frontend
```

Multiple tags:

```bash
nexterm tag portfolio frontend react personal
```

---

## Tag search

```bash
nexterm tag <tag>
```

Example:

```bash
nexterm tag frontend
```

Returns all projects with the tag.

---

# 24. Stack Management

## `nexterm stack up`

Start a project's complete service stack.

```bash
nexterm stack up <project>
```

Example:

```text
PostgreSQL
✓ Started

Redis
✓ Started

Backend
✓ Started

Frontend
✓ Started
```

---

## `nexterm stack down`

Stop the project's stack.

```bash
nexterm stack down <project>
```

---

## `nexterm stack restart`

Restart the stack.

```bash
nexterm stack restart <project>
```

---

## `nexterm stack status`

Show service status.

```bash
nexterm stack status <project>
```

---

## `nexterm stack logs`

Display project service logs.

```bash
nexterm stack logs <project>
```

---

# 25. AI Commands

AI is an optional intelligence layer.

The base terminal must work without AI.

## `nexterm ai`

Open the AI interface.

```bash
nexterm ai
```

---

## `nexterm ai status`

Show AI runtime/model status.

```bash
nexterm ai status
```

---

## `nexterm ai models`

List available models.

```bash
nexterm ai models
```

---

## `nexterm ai install`

Install the configured local AI runtime/model.

```bash
nexterm ai install
```

---

## `nexterm ai remove`

Remove an optional model/runtime.

```bash
nexterm ai remove
```

---

# 26. AI Ask

## `nexterm ask`

Ask the AI about the current environment/project.

```bash
nexterm ask
```

Or:

```bash
nexterm ask "Why isn't my backend starting?"
```

The AI should receive structured NexTerm project context rather than blindly scanning the entire filesystem.

---

# 27. AI Explain

## `nexterm explain`

Explain a project.

```bash
nexterm explain <project>
```

Expected:

```text
Project:
Invoice

Frontend:
React

Backend:
FastAPI

Database:
PostgreSQL

Authentication:
JWT

AI:
Ollama

Entry Points:
frontend/src/main.tsx
backend/main.py
```

---

# 28. AI Fix

## `nexterm fix`

Analyze and propose a fix.

```bash
nexterm fix <project>
```

Expected workflow:

```text
Read logs
    ↓
Inspect project
    ↓
Identify problem
    ↓
Run tests
    ↓
Generate proposed patch
    ↓
Show diff
    ↓
Request approval
    ↓
Apply
    ↓
Verify
```

AI must NOT silently modify files.

---

# 29. Guardian

## `nexterm guardian`

Run the complete Guardian system.

```bash
nexterm guardian
```

---

## `nexterm guardian check`

Run all validation checks.

```bash
nexterm guardian check
```

---

## `nexterm guardian pre-push`

Run the exact pre-push validation.

```bash
nexterm guardian pre-push
```

---

## `nexterm guardian status`

Show Guardian configuration/status.

```bash
nexterm guardian status
```

---

## `nexterm guardian report`

Show the latest Guardian report.

```bash
nexterm guardian report
```

---

# 30. Release Commands

## `nexterm release check`

Check release readiness.

```bash
nexterm release check
```

Checks:

* version
* metadata
* tests
* security
* build
* package contents
* Git state
* release configuration

---

## `nexterm release verify`

Perform a complete release verification.

```bash
nexterm release verify
```

---

## `nexterm release build`

Build release artifacts.

```bash
nexterm release build
```

Expected:

```text
dist/
├── nexterm-X.Y.Z-py3-none-any.whl
└── nexterm-X.Y.Z.tar.gz
```

---

## `nexterm release status`

Show release status.

```bash
nexterm release status
```

This must NOT publish automatically.

---

# 31. Shell History

NexTerm must support interactive history.

Commands entered:

```text
npm install
npm run dev
git status
cd portfolio
```

must be recoverable with:

```text
↑
↓
```

History should support:

* previous command
* next command
* history persistence if configured
* history navigation without corrupting the input line

---

# 32. Keyboard Editing

The interactive shell must support:

```text
Backspace
Delete
Ctrl+Backspace
Ctrl+Left
Ctrl+Right
Home
End
Ctrl+A
Ctrl+E
Ctrl+C
Ctrl+L
Arrow Up
Arrow Down
Arrow Left
Arrow Right
Tab
Enter
```

Especially:

```text
Ctrl+Backspace
```

must delete the previous word rather than inserting:

```text
^W
```

or other control characters.

---

# 33. Tab Completion

Tab completion must support:

```text
cd <TAB>
```

and:

```text
cd pro<TAB>
```

It must provide directory suggestions.

Example:

```text
C:\Projects>

cd pro<TAB>
```

Possible results:

```text
portfolio
projects
profile
```

Tab completion should also eventually support:

* filesystem paths
* directories
* files
* NexTerm project names
* NexTerm commands
* command arguments where practical

---

# 34. Command Error Handling

Every command must have clean error handling.

Bad:

```text
Traceback (most recent call last):
...
```

Preferred:

```text
ERROR

Command:
npm run dev

Reason:
npm was not found on PATH.

Suggested action:
Install Node.js or add npm to PATH.
```

Errors should identify:

1. What failed.
2. Why it failed.
3. What the user can do.

---

# 35. Exit Codes

Commands must preserve meaningful exit status.

Successful:

```text
exit code 0
```

Failure:

```text
non-zero exit code
```

NexTerm must not convert normal subprocess failures into application crashes.

---

# 36. Environment Handling

NexTerm must correctly inherit the environment for child processes.

Verify:

```text
PATH
environment variables
working directory
user environment
project environment
```

External commands must see the same required environment as they would from a normal shell.

---

# 37. Command Execution Rules

For every command:

```text
Parse
  ↓
Determine NexTerm command?
  │
  ├── YES → NexTerm command handler
  │
  └── NO
       ↓
Resolve system executable
       ↓
Execute through OS
       ↓
Stream stdout/stderr
       ↓
Return exit code
```

Do not use AI to decide how to execute normal deterministic commands.

AI should only be involved when reasoning is actually required.

---

# 38. Safety Rules

The following commands/actions require additional caution:

```text
rmdir
rm
git reset
git clean
git rebase
docker system prune
nexterm unregister
nexterm ai remove
nexterm fix
```

Never silently perform destructive operations.

AI-generated modifications must require explicit user approval.

---

# 39. Command Verification Requirement

Every command in this document must have an individual verification test.

The verification system must record:

```text
Command
Category
Expected behavior
Actual behavior
Exit code
Platform
Result
Error
```

Allowed results:

```text
PASS
FAIL
BLOCKED
NOT INSTALLED
NOT APPLICABLE
```

Do not mark a command as `PASS` merely because its parser recognizes it.

---

# 40. Pre-Push Requirement

Before:

```bash
git push
```

NexTerm Guardian must verify the command system.

Required checks:

```text
Core shell
    ↓
Filesystem commands
    ↓
Keyboard/input
    ↓
Tab completion
    ↓
Native command passthrough
    ↓
Development commands
    ↓
Project commands
    ↓
Project detection
    ↓
Project lifecycle
    ↓
Doctor
    ↓
Stack
    ↓
AI
    ↓
Guardian
    ↓
Release
    ↓
Security
    ↓
Build
    ↓
Final verification
```

If a critical test fails:

```text
BLOCK GIT PUSH
```

If all required checks pass:

```text
ALLOW GIT PUSH
```

---

# 41. Command Priority

## P0 — Must work before first release

```text
nexterm
nexterm --version
nexterm --help

pwd
ls
dir
cd
cd ..
mkdir
clear
cls
echo
exit

Tab
Backspace
Ctrl+Backspace
Ctrl+Left
Ctrl+Right
Home
End
Ctrl+C
Arrow Up
Arrow Down

node
npm
python
pip
git
docker

projects
find
search
open
start
status
info
doctor
tag
register
unregister
rescan
index

guardian
guardian check
guardian pre-push

release check
release verify
release build
```

---

# 42. P1 — Required for the complete platform

```text
stack up
stack down
stack restart
stack status
stack logs

ai
ai status
ai models
ai install

ask
explain
fix

guardian status
guardian report

release status
```

---

# 43. P2 — Extended Ecosystem Support

```text
pnpm
yarn
bun

java
javac
mvn
gradle

cargo
rustc
go

make
cmake

curl
ssh
ffmpeg
code
```

These should primarily work through native shell passthrough rather than custom NexTerm implementations.

---

# 44. Final Command Philosophy

NexTerm must feel like:

```text
A NORMAL TERMINAL
        +
PROJECT AWARENESS
        +
AUTOMATION
        +
DIAGNOSTICS
        +
WORKSPACE MANAGEMENT
        +
OPTIONAL AI
        +
RELEASE/GUARDIAN SYSTEM
```

The user should be able to do:

```text
nexterm C:\Projects>

pwd
ls
cd portfolio

npm install
npm run dev

git status
docker compose up

nexterm start invoice
nexterm doctor invoice
nexterm find react
nexterm status
nexterm guardian check
```

without leaving NexTerm.

The core principle is:

> **If a command normally works in the user's operating-system terminal, NexTerm should allow it to work inside NexTerm unless there is a documented reason not to.**

NexTerm-native functionality should extend the terminal rather than replace it.

```
```
