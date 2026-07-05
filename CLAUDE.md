# keel - agent guide (developing keel itself)

keel is a domain-agnostic TOON graph engine ("a spec as a cacheable graph"), shipped as a
Claude Code skill. Pure-Python-stdlib CLI. This file is for hacking on keel, not using it.

## Source of truth vs the install (READ FIRST)
Edit the SOURCES here, never the deployed copy:
- engine/      the tool (cli.py + modules)   -> installs as scripts/
- skill/       SKILL.md + references/
- completion/  _keel (zsh)
`./deploy.sh` composes these into ~/.claude/skills/keel/ - the copy the loaded skill runs
from. That install is a BUILD ARTIFACT: never edit it, change the source and re-run
./deploy.sh. Edits to the installed copy vanish on next deploy and never reach git.

## Stack & commands
- Python 3.14, uv-managed venv. Tests: `uv run pytest` (tests/test_engine.py).
- engine/ is pure Python stdlib - no third-party imports, keep it that way.
- Runtime dep: ripgrep (`rg`) - refs/check/status use it for graph<->code drift.

## Output contract (this project has no logging)
All output goes through `emit.py`:
- stdout = PAYLOAD: TOON (round-trips render.parse_toon), pure and pipeable.
- stderr = diagnostics/errors: emit.die / emit.nxt.
No .log files. Honor the 10 AXI principles (README "Agent-facing output"; code cites P1..P10).
Never hand-edit rendered output (*.view.md) - it is built from the graph.

## Code style
- Module header = first-line docstring `"""name: one-line purpose"""` for engine/*.py;
  shell scripts use `# ABOUTME:` (line 1 only - it is a grep handle).
- black, 88 cols; section separators (# ==== CONFIG ====) on longer modules.
- Explicit arg names; `Path` objects, not raw strings; dataclass when config > 3 params;
  consistent arg names across functions that share a physical meaning.

## Working rules
- Smallest reasonable change; no unrelated edits (note tech debt inline instead).
- Preserve comments unless provably false; keep them evergreen (no temporal context).
- No bloat .md files - README.md is the only root doc. Prefer a README section or a code
  docstring over a new file. Plain dash '-', never em dash.
