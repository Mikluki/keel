#!/usr/bin/env bash
# ABOUTME: Install the keel skill into the user's global skills dir
# (~/.claude/skills/keel) as a real, exact copy - discoverable in every session and
# self-contained. Composes two repo sources into one installed skill; re-run to reinstall
# after editing either. Diagnostics -> stderr; stdout stays empty (no payload).
#
# Sources (SSOT, tracked):  <repo>/skill/       (SKILL.md, references/)
#                           <repo>/engine/      (cli.py + modules)
#                           <repo>/completion/  (_keel, zsh)
# Dest (install):           ~/.claude/skills/keel/           (SKILL.md, references/, scripts/)
#                           <oh-my-zsh custom>/completions/   (symlink to _keel, best-effort)
#
# Requires: rsync, python3. ripgrep (rg) is needed at RUNTIME for drift/check/status.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # this repo's root
SKILL_SRC="$REPO_DIR/skill"                                # SKILL.md + references/
ENGINE="$REPO_DIR/engine"                                  # the tool
DEST="$HOME/.claude/skills/keel"                            # global install

command -v rsync >/dev/null    || { echo "ERROR: rsync not found." >&2; exit 1; }
[ -f "$SKILL_SRC/SKILL.md" ]   || { echo "ERROR: $SKILL_SRC/SKILL.md missing - run from a keel checkout." >&2; exit 1; }
[ -f "$ENGINE/cli.py" ]        || { echo "ERROR: $ENGINE/cli.py missing." >&2; exit 1; }

# Symlink safety: NEVER write through a symlinked dest into some other tree (an old
# editable install once left DEST as a symlink into the repo; rsync/rm through it is how
# real files got clobbered). Replace any symlink at DEST or DEST/scripts with a real dir.
[ -L "$DEST" ]         && rm -f "$DEST"
mkdir -p "$DEST"
[ -L "$DEST/scripts" ] && rm -f "$DEST/scripts"

# 1. skill docs (SKILL.md, references/, ...). --exclude protects DEST/scripts/ from --delete.
rsync -a --delete --exclude='scripts' --exclude='__pycache__/' --exclude='*.py[cod]' "$SKILL_SRC/" "$DEST/"
# 2. the engine becomes the skill's self-contained scripts/.
rsync -a --delete --exclude='__pycache__/' --exclude='*.py[cod]' "$ENGINE/" "$DEST/scripts/"

# Smoke test: the INSTALLED copy must run, and the referenced grammar must be present.
python3 "$DEST/scripts/cli.py" -h >/dev/null || { echo "ERROR: smoke test failed on $DEST/scripts/cli.py -h" >&2; exit 1; }
[ -f "$DEST/references/schema.md" ] || { echo "ERROR: references/schema.md did not install." >&2; exit 1; }

echo "  installed keel skill -> $DEST" >&2
echo '  OK: python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py -h runs; references/schema.md present' >&2

# 3. zsh completion, best-effort: keel works fine without it, this only adds tab-completion
# for slice/slug args. Symlinked (not copied), so editing completion/_keel takes effect on
# the next shell, same as the ~/.local/bin/keel PATH shim. Only oh-my-zsh is auto-detected
# (its custom/completions dir is already on $fpath with compinit wired up); anything else
# gets a manual one-liner instead of a guessed-at fpath location.
COMPLETION_SRC="$REPO_DIR/completion/_keel"
COMPLETION_DEST_DIR=""
if [ -n "${ZSH_CUSTOM:-}" ]; then
    COMPLETION_DEST_DIR="$ZSH_CUSTOM/completions"
elif [ -d "$HOME/.oh-my-zsh" ]; then
    COMPLETION_DEST_DIR="$HOME/.oh-my-zsh/custom/completions"
fi

if [ -n "$COMPLETION_DEST_DIR" ]; then
    mkdir -p "$COMPLETION_DEST_DIR"
    ln -sf "$COMPLETION_SRC" "$COMPLETION_DEST_DIR/_keel"
    echo "  installed zsh completion -> $COMPLETION_DEST_DIR/_keel (new shells pick it up)" >&2
else
    echo "  zsh completion not auto-installed (no oh-my-zsh detected)." >&2
    echo "  to enable: add 'fpath+=($REPO_DIR/completion)' before compinit in your .zshrc." >&2
fi
