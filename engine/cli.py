#!/usr/bin/env python3
"""keel - one entry point for the spec-graph loop tools.

    keel render  [slices...]                 human view
    keel lint    [slices...]                 graph-internal consistency gate
    keel drift   [slices...] --code-root R   graph<->code drift gate (ripgrep)
    keel status  [slices...] --code-root R   divergence dashboard
    keel todo    [goal] [slices...] --code-root R   ranked worklist: what next (fix > ready lanes > decide)
    keel matrix  [slices...] [pivot "<a> x <b>"] --code-root R   coverage pivot (no axes: rank candidates)
    keel check   [slices...] --code-root R   lint + drift (the loop's CHECK step)
    keel context <node|col=val|file#sym> [slices...] [--code-root R]   1-hop edit context (PICK step); with R refs resolve inline; col=val = a node SET's induced subgraph; file#sym reverses: who pins that code
    keel find    <source-path>               which toons/ container anchors a file
    keel new     <anchor> [--code-root R]    scaffold a fresh toons/<slug>/ (cold start)

slices default to *.graph.toon in the cwd; a directory arg is globbed. In a repo with a
`toons/` dir, a bare `<slug>` (e.g. `check scripts-viz-lenses`) resolves to that
container and defaults --code-root to the repo root - no long paths on every call.
--code-root (-cc) is the CODE root for ref resolution (your crate/package).
Every command takes --toon (structured body) and -h/--help (its own reference); -hh also
lists the human/setup commands (view, index, watch).

Output convention (deliberate exception to the repo's logging rule): stdout is PAYLOAD -
the agent-facing data / return value - so it stays pure and TOON-able and pipes cleanly.
Diagnostics and errors go to stderr. Never route payload through logging.
"""
import ast
import runpy
import sys
from pathlib import Path

import emit
import containers

HERE = Path(__file__).resolve().parent
# init / view / index / watch are HUMAN commands: each dispatches and has its own -h, but is
# kept OUT of the agent-facing -h listing (shown only under -hh) to keep the agent's context
# lean - they bootstrap / preview / roll up / monitor, none part of the pull-based agent loop.
SCRIPTS = {'render': 'render.py', 'view': 'view.py', 'lint': 'lint.py', 'drift': 'drift.py',
           'status': 'status.py', 'todo': 'todo.py', 'matrix': 'matrix.py',
           'context': 'context.py', 'index': 'index.py', 'find': 'find.py', 'new': 'new.py',
           'init': 'init.py', 'watch': 'watch.py'}

HUMAN_HELP = """
Human / setup commands (kept out of -h to keep the agent loop lean):

    keel init    [target]              stand up the sibling <repo>-keel/ worktree (split-repo)
    keel view    [dir]                  materialize a graph dir's render -> <name>.view.md preview
    keel index   [toons dir]           derived repo-wide roll-up + slug invariant
    keel watch   [dir]                  live: poll toons/, refresh previews + lint on change
"""


def run(script, argv):
    sys.argv = [script, *argv]
    try:
        runpy.run_path(str(HERE / script), run_name='__main__')
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (1 if e.code else 0)


def strip_root(argv):
    out, i = [], 0
    while i < len(argv):
        if argv[i] in emit.ROOT_FLAGS:
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def docstring(script):
    """A subcommand's own help = its module docstring (P10), read without importing."""
    return ast.get_docstring(ast.parse((HERE / script).read_text())) or f"(no help for {script})"


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--list-slugs':
        # Shell-completion helper (see completion/_keel) - deliberately absent from -h/-hh,
        # it is not a loop command, just the current repo's toons/ slugs, one per line.
        toons = containers.find_toons_root()
        if toons is not None:
            for d in containers.iter_containers(toons):
                print(d.name)
        return
    if len(sys.argv) >= 2 and sys.argv[1] == '-hh':
        print((__doc__ or '') + HUMAN_HELP)   # full listing incl. the human/setup commands
        return
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    wants_help = '-h' in rest or '--help' in rest
    if not wants_help:
        rest = containers.expand_slugs(rest, cmd)   # bare <slug> -> toons/<slug>/ (+ --code-root)

    if cmd == 'check':
        if wants_help:
            print("check: lint + drift - the loop's CHECK step (lint first, then drift).\n")
            print(docstring('lint.py') + '\n\n' + docstring('drift.py'))
            return
        sys.exit(max(run('lint.py', strip_root(rest)), run('drift.py', rest)))
    if cmd in SCRIPTS:
        if wants_help:
            print(docstring(SCRIPTS[cmd]))
            return
        sys.exit(run(SCRIPTS[cmd], rest))
    emit.die('UNKNOWN_COMMAND', f"unknown command: {cmd} (try -h)")


if __name__ == '__main__':
    main()
