#!/usr/bin/env python3
"""watch: an ambient monitor over a .toons/ tree - the human-facing live loop (replaces the hook).

Instead of gating the agent on every edit, watch polls the (tiny) .toons/ tree; when a
container's slice/body settles it refreshes that container's <name>.view.md preview, re-lints
it, prints a live status line, and maintains .toons/_watch.status so anyone can pull the latest
verdict cheaply. The agent is never interrupted - it pulls status on its own schedule.

Watches ONLY .toons/ (graph-internal consistency + previews). At this scale a poll is ample, so
there is no dependency and no daemon. Code<->graph drift (`refs`, a ripgrep scan of the code
root) stays a PULL gate you run at CHECK; watch never scans the code root.

    python watch.py                 # watch the .toons/ enclosing the cwd
    python watch.py path/to/repo    # watch that repo's .toons/     (Ctrl-C to stop)
"""
import subprocess
import sys
import time
from pathlib import Path

import emit
import containers

HERE = Path(__file__).resolve().parent
POLL = 0.3          # seconds between scans; the tree is tiny, so this is cheap
DEBOUNCE = 0.2      # settle window: coalesce a burst of saves into one refresh
STATUS_FILE = '_watch.status'


def scan(toons):
    """Snapshot {path: mtime} of every graph/view/body SOURCE under .toons/ (skip derived files)."""
    snap = {}
    for p in toons.rglob('*'):
        if not p.is_file() or p.name.startswith('_') or p.name.endswith('.view.md'):
            continue                                # '_*' and *.view.md are our own derived output
        if p.suffix == '.toon' or (p.parent.name == 'bodies' and p.suffix == '.md'):
            snap[p] = p.stat().st_mtime
    return snap


def container_of(path, toons):
    """The .toons/<slug>/ dir a changed file belongs to."""
    return toons / path.relative_to(toons).parts[0]


def cli(cmd, container):
    return subprocess.run([sys.executable, str(HERE / 'cli.py'), cmd, str(container)],
                          capture_output=True, text=True)


def process(container):
    """Refresh the container's preview, then lint it. Returns (ok, one-line summary)."""
    cli('view', container)                          # rewrite <name>.view.md (render errors land in it)
    out = cli('lint', container)
    summary = out.stdout.splitlines()[0] if out.stdout.strip() else '(no output)'
    return out.returncode == 0, summary


def stamp():
    return time.strftime('%H:%M:%S')


def report(ok, slug, summary):
    print(f"{stamp()}  {'OK  ' if ok else 'FAIL'}  {slug}: {summary}", file=sys.stderr)


def write_status(toons, verdicts):
    """Overwrite .toons/_watch.status with the current verdict for every container (pull target)."""
    lines = [f"# keel watch  {toons}  (updated {stamp()})"]
    for slug in sorted(verdicts):
        ok, summary, ts = verdicts[slug]
        lines.append(f"{ts}  {'OK  ' if ok else 'FAIL'}  {slug}  {summary}")
    (toons / STATUS_FILE).write_text('\n'.join(lines) + '\n')


def watch(toons):
    verdicts = {}
    for c in containers.iter_containers(toons):      # baseline pass so the status file starts complete
        ok, summary = process(c)
        verdicts[c.name] = (ok, summary, stamp())
        report(ok, c.name, summary)
    write_status(toons, verdicts)
    print(f"{stamp()}  watching {toons}  (poll {POLL}s, Ctrl-C to stop)", file=sys.stderr)

    snap = scan(toons)
    dirty, last = set(), None
    while True:
        time.sleep(POLL)
        cur = scan(toons)
        changed = [p for p in set(cur) | set(snap) if cur.get(p) != snap.get(p)]
        for p in changed:
            try:
                dirty.add(container_of(p, toons))
            except (ValueError, IndexError):
                pass                                 # a file outside any <slug>/ - ignore
        if changed:
            last = time.monotonic()                  # a fresh edit resets the settle window
        snap = cur
        if dirty and last is not None and time.monotonic() - last >= DEBOUNCE:
            for c in sorted(dirty):
                if c.is_dir():
                    ok, summary = process(c)
                    verdicts[c.name] = (ok, summary, stamp())
                else:
                    verdicts.pop(c.name, None)        # container was deleted
                    ok, summary = False, 'container removed'
                report(ok, c.name, summary)
            write_status(toons, verdicts)
            dirty, last = set(), None


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='watch')
    start = Path(args.positional[0]) if args.positional else Path('.')
    toons = containers.find_toons_root(start)
    if toons is None:
        emit.die('NO_TOONS', f"no .toons/ at or above {start} - nothing to watch", exit_code=3)
    try:
        watch(toons)
    except KeyboardInterrupt:
        print(f"\n{stamp()}  stopped", file=sys.stderr)


if __name__ == '__main__':
    main()
