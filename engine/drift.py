#!/usr/bin/env python3
"""drift: verify every `ref` edge (graph node -> code symbol) exists.

The graph<->code drift guard for the dev loop. A `ref` edge's target is a code
coordinate: `path/file.rs#symbol`, `path/file.py` (file only), or a bare `symbol`
searched across the root. A symbol is any definition, module-level constants
included (py `NAME = ...`/`NAME: t = ...`, rust `const`/`static`) - so a chosen
number lives in code and the graph refs it by name: the value churns with zero
graph diff, a rename fails the gate. Resolution uses ripgrep with Rust/Python
definition patterns, so the agent never greps by hand and a renamed or missing
symbol FAILS the gate instead of silently rotting the design.

It also guards the REVERSE direction (membrane_leaks): the reference is one-way, so
code must never name the graph back. A `.graph.toon` path, a `toons/` reference, or a
`keel node/decision ...` comment in the code tree is an un-checked back-reference that
rots green and seeds design prose leaking into comments - it FAILS the gate too.

    python drift.py *.graph.toon --code-root ../my-crate
    python drift.py toons/<slug> --code-root ../my-crate --toon     # structured body for an agent
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import containers
import emit
from render import SYSTEM_TABLES, load_union, resolve_paths, state_of


def rust_pat(sym):
    s = re.escape(sym)
    pre = r'(pub(\([^)]*\))?\s+)?((async|unsafe|default|const|extern\s+"[^"]*")\s+)*'
    kw = r'(fn|struct|enum|trait|type|const|static|mod|union)'
    return rf'^\s*{pre}{kw}\s+{s}\b|^\s*macro_rules!\s+{s}\b'


def py_pat(sym):
    s = re.escape(sym)
    return rf'^\s*(async\s+)?(def|class)\s+{s}\b|^{s}\s*[:=]'


PAT = {'.rs': rust_pat, '.py': py_pat}
RG_LANG = {'.rs': 'rust', '.py': 'py'}

# The reverse membrane. keel refs code ONE WAY (the ref edges above); code must
# never name the graph back. A `.graph.toon` path, a `toons/` reference, or a
# `keel node/decision ...` comment in code is an un-checked back-reference: it rots
# green (a renamed node silently lies) and normalizes design prose leaking into
# comments where nothing checks it. A hit in CODE is graph-only vocabulary = a leak.
MEMBRANE_PAT = (r'\.(graph|views|results)\.toon'
                r'|\btoons/'
                r'|\bkeel:'
                r'|\bkeel (node|graph|decision|invariant|spec|slice|container|slug)')

# Never scan keel's OWN artifacts (the graph legitimately speaks graph-vocabulary),
# wherever they sit: the toons/ tree co-located, or a stray slice in the code root.
MEMBRANE_EXCLUDE = tuple(
    x for g in ('**/toons/**', '*.graph.toon', '*.views.toon', '*.results.toon',
                '*.view.md', '_index.toon', '_watch.status')
    for x in ('--glob', f'!{g}'))


def rg(pattern, *targets, extra=()):
    cmd = ['rg', '--no-heading', '-n', '--color=never', *extra, '-e', pattern, *map(str, targets)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def membrane_leaks(root):
    """Every code->graph back-reference under `root` (file:line:content); the reverse of
    drift. drift checks graph->code refs EXIST; this checks code->graph refs do NOT.
    Split-repo puts the graph off the code tree, so any hit is a leak; co-located, the
    toons/ tree and keel artifacts are excluded so only a real source leak matches.
    """
    return rg(MEMBRANE_PAT, root, extra=('-i', *MEMBRANE_EXCLUDE))


def resolve(target, root):
    """Return (status, evidence) for one ref target.

    evidence is a single hit line for OK, the LIST of hits for AMBIGUOUS (so the
    caller can size-hint + truncate it), and None for the MISSING states.
    """
    if '#' in target:
        rel, sym = target.split('#', 1)
    elif '/' in target or Path(target).suffix in PAT:
        rel, sym = target, None
    else:
        rel, sym = None, target            # bare symbol -> search the whole root

    if rel is not None:
        f = root / rel
        if not f.exists():
            return 'MISSING-FILE', str(f)
        if sym is None:
            return 'OK', 'file exists'
        hits = rg(PAT.get(f.suffix, py_pat)(sym), f)
        return ('OK', hits[0]) if hits else ('MISSING-SYM', None)

    hits = []
    for ext, lang in RG_LANG.items():
        hits += rg(PAT[ext](sym), root, extra=('-t', lang))
    if len(hits) == 1:
        return 'OK', hits[0]
    if len(hits) > 1:
        return 'AMBIGUOUS', hits
    return 'MISSING-SYM', None


def evidence_str(status, ev, full):
    """Flatten one resolve() evidence into a single display line (P3 truncation)."""
    if status == 'AMBIGUOUS':
        return emit.head(ev, len(ev) if full else 3, 'defs')
    return ev if ev and ev != 'file exists' else ''


def jump_of(target, status, ev, root):
    """(location, snippet) for one resolve(): the assembled jump handle + the bare match.

    location is the root-relative `file:line` a human clicks / an agent Reads at ('' when
    there is none); snippet is the matched line with rg's prefixes stripped, since the
    location owns them. Assembled from resolve()'s evidence shapes: a file-scoped hit is
    `line:content` (rg omits the filename), a root-wide bare-symbol hit is `path:line:content`.
    Non-OK statuses have no location; their evidence passes through evidence_str untouched.
    """
    if status != 'OK':
        return '', None
    if '#' in target:
        rel = target.split('#', 1)[0]
    elif '/' in target or Path(target).suffix in PAT:
        return target, None                # file-only ref: the file IS the location
    else:
        rel = None                         # bare symbol: the path comes from the hit
    if rel is not None:
        line, _, content = ev.partition(':')
        return (f"{rel}:{line}", content) if line.isdigit() else (rel, ev)
    p, line, content = ev.split(':', 2)
    try:
        p = str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        pass                               # hit outside root: keep the path as reported
    return f"{p}:{line}", content


def main():
    if not shutil.which('rg'):
        emit.die('NO_RIPGREP', 'drift needs ripgrep (rg) on PATH', exit_code=3)
    args = emit.parse(sys.argv[1:], cmd='drift')
    paths = resolve_paths(args.positional)
    root = emit.default_root(args.root, paths)
    slices, tables, _ = load_union(paths)
    state_by = {r['id']: state_of(r) for name, rows in tables.items()
                if name not in SYSTEM_TABLES for r in rows if 'id' in r}
    refs = [e for e in tables.get('edges', []) if e['kind'] == 'ref']

    rows, bad, muted = [], 0, 0
    for e in refs:
        status, ev = resolve(e['to'], root)
        st = state_by.get(e['from'], 'canon')
        if status != 'OK':
            if st == 'canon':          # only canon drift fails the gate
                bad += 1
            else:                      # an explore/dropped spike ref: informational, never fatal
                muted += 1
        rows.append({'status': status, 'state': st, 'from': e['from'], 'to': e['to'],
                     'evidence': evidence_str(status, ev, args.full)})

    leaks = membrane_leaks(root)   # reverse membrane: code must never name the graph
    n_ok = sum(1 for r in rows if r['status'] == 'OK')
    names = ', '.join(n for n, _, _ in slices)
    if args.toon:
        print(emit.toon(
            {'slices': names, 'refs': len(refs), 'resolved': n_ok,
             'failing': bad, 'muted': muted, 'leaks': len(leaks), 'root': root},
            {'refs': (['status', 'state', 'from', 'to', 'evidence'], rows),
             'membrane': (['hit'], [{'hit': ln} for ln in leaks])}))
    else:
        print(f"drift [{names}]: {len(refs)} ref edges, {n_ok} resolved, "
              f"{bad} failing (canon), {muted} muted (explore/dropped), "
              f"{len(leaks)} membrane leak(s), root={root}")
        if not refs:
            print("  0 ref edges - no graph node points at code yet")
        for r in rows:
            tail = f"   [{r['evidence']}]" if r['evidence'] else ''
            tag = '' if r['state'] == 'canon' else f" ({r['state']})"
            print(f"  {r['status']:12} {r['from']:14}{tag} -> {r['to']}{tail}")
        if leaks:
            print("  MEMBRANE: code names the graph (it must not - the graph refs code one "
                  "way; a back-reference rots green):")
            for ln in (leaks if args.full else leaks[:12]):
                print(f"     x {ln}")
            if not args.full and len(leaks) > 12:
                print(f"     (+{len(leaks) - 12} more; --full)")

    slice_args = ' '.join(containers.display_arg(a) for a in args.positional) or '.'
    if bad or leaks:
        if bad:
            emit.nxt("point each failing canon ref at real code (ref,<node>,file#symbol), "
                     "or set the node state:explore/dropped, then re-run keel check",
                     toon=args.toon)
        else:
            emit.nxt("delete the keel reference from code - the graph refs code one way, never "
                     "the reverse (keep the logic, drop the comment/path), then re-run keel check",
                     toon=args.toon)
        sys.exit(1)
    emit.nxt(f"keel status {slice_args} --code-root <code> for the divergence dashboard",
             toon=args.toon, guide=True)


if __name__ == '__main__':
    main()
