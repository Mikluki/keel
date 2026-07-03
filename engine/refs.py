#!/usr/bin/env python3
"""ref-resolve: verify every `ref` edge (graph node -> code symbol) exists.

The graph<->code drift guard for the dev loop. A `ref` edge's target is a code
coordinate: `path/file.rs#symbol`, `path/file.py` (file only), or a bare `symbol`
searched across the root. Resolution uses ripgrep with Rust/Python definition
patterns, so the agent never greps by hand and a renamed or missing symbol FAILS
the gate instead of silently rotting the design.

    python refs.py *.graph.toon --root ../my-crate
    python refs.py .toons/<slug> --root ../my-crate --toon     # structured body for an agent
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

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


def rg(pattern, *targets, extra=()):
    cmd = ['rg', '--no-heading', '-n', '--color=never', *extra, '-e', pattern, *map(str, targets)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


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


def main():
    if not shutil.which('rg'):
        emit.die('NO_RIPGREP', 'ref-resolve needs ripgrep (rg) on PATH', exit_code=3)
    args = emit.parse(sys.argv[1:], cmd='refs')
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

    n_ok = sum(1 for r in rows if r['status'] == 'OK')
    names = ', '.join(n for n, _, _ in slices)
    if args.toon:
        print(emit.toon(
            {'slices': names, 'refs': len(refs), 'resolved': n_ok,
             'failing': bad, 'muted': muted, 'root': root},
            {'refs': (['status', 'state', 'from', 'to', 'evidence'], rows)}))
    else:
        print(f"ref-resolve [{names}]: {len(refs)} ref edges, {n_ok} resolved, "
              f"{bad} failing (canon), {muted} muted (explore/dropped), root={root}")
        if not refs:
            print("  0 ref edges - no graph node points at code yet")
        for r in rows:
            tail = f"   [{r['evidence']}]" if r['evidence'] else ''
            tag = '' if r['state'] == 'canon' else f" ({r['state']})"
            print(f"  {r['status']:12} {r['from']:14}{tag} -> {r['to']}{tail}")

    slice_args = ' '.join(args.positional) or '.'
    if bad:
        emit.nxt("point each failing canon ref at real code (ref,<node>,file#symbol), "
                 "or set the node state:explore/dropped, then re-run check", toon=args.toon)
        sys.exit(1)
    emit.nxt(f"status {slice_args} --root <code> for the divergence dashboard", toon=args.toon)


if __name__ == '__main__':
    main()
