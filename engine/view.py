#!/usr/bin/env python3
"""view: materialize a graph dir's human render to <dirname>.view.md (the live-preview file).

`render` prints the human view to stdout (a payload you pipe); `view` writes that same view
to a stable file next to the graph, so an editor can keep it open and hot-reload it. This is
the manual regen command AND what `watch` calls when a graph changes, so the rendered
view never drifts from the graph. A derived artifact - gitignored, never hand-edited.

    python view.py .toons/<slug>        # -> .toons/<slug>/<slug>.view.md
    python view.py                      # the graph dir in the cwd -> <cwd>.view.md

On a render failure the file gets an error banner instead of going stale, so a broken
mid-edit graph is visible in the preview rather than silently frozen.
"""
import subprocess
import sys
from pathlib import Path

import emit
from render import dir_slices

HERE = Path(__file__).resolve().parent


def render_result(target):
    """Run `render` on a graph dir, capturing its human markdown (stdout) + status."""
    argv = ['render', str(target)]
    return subprocess.run([sys.executable, str(HERE / 'cli.py'), *argv],
                          capture_output=True, text=True)


def strip_next_hint(text):
    """Drop render's trailing `next:` diagnostic (P9) so the written view is pure spec."""
    lines = text.rstrip().splitlines()
    while lines and (lines[-1].startswith('next:') or not lines[-1].strip()):
        lines.pop()
    return '\n'.join(lines) + '\n'


def banner(target, err):
    """The placeholder written into the view when render fails - no silent stale preview."""
    return (f"# Render FAILED - {target}\n\n"
            f"The graph could not be rendered (a broken or mid-edit slice). Fix the graph;\n"
            f"this preview refreshes on the next successful render.\n\n"
            f"```\n{err.strip()}\n```\n")


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='view')
    target = Path(args.positional[0]) if args.positional else Path('.')
    if not target.is_dir():
        target = target.parent          # tolerate a slice/body path - render its dir
    if not dir_slices(target):
        emit.die('NO_SLICES', f"no *.graph.toon in {target} - nothing to render", exit_code=3)

    out_path = target / f"{target.resolve().name}.view.md"
    res = render_result(target)
    if res.returncode == 0:
        out_path.write_text(strip_next_hint(res.stdout))
        print(out_path)                 # payload: the file we produced
        emit.nxt(f"open {out_path} in your editor - it refreshes on every graph edit")
        return 0
    out_path.write_text(banner(target, res.stderr or res.stdout))
    emit.die('RENDER_FAILED', f"render failed; wrote an error banner to {out_path}",
             exit_code=1)


if __name__ == '__main__':
    main()
