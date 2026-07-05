#!/usr/bin/env python3
"""pack: the 1-hop edit context for a single node - what an agent loads to edit it.

Emits the node's attributes + bodies/ prose + every edge touching it (in & out =
the blast radius) + every invariant/decision that `touches` it + its code refs.
~20 lines instead of the whole spec - this is the loop's PICK step.

    python pack.py <node-id> [slices...]
    python pack.py <node> .toons/<slug> --toon      # structured body for an agent
    python pack.py <node> .toons/<slug> --brief     # truncate the prose body (full by default)
"""
import sys
from pathlib import Path

import emit
from render import SYSTEM_TABLES, load_union, resolve_paths, split, state_of

BODY_LINES = 12          # prose body truncated past this under --brief; full by default


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='pack')
    if not args.positional:
        emit.die('USAGE', 'pack needs a node id: pack <node-id> [slices...]')
    nid, paths = args.positional[0], resolve_paths(args.positional[1:])
    slices, tables, prov = load_union(paths)

    row, table = None, None
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            if r.get('id') == nid:
                row, table = r, tname
    if row is None:
        emit.die('NODE_NOT_FOUND', f"node '{nid}' not in any loaded slice", exit_code=3)
    st = state_of(row)

    attrs = [{'key': k, 'value': v} for k, v in row.items() if k != 'id']
    edges = ([{'dir': 'out', 'kind': e['kind'], 'other': e['to']}
              for e in tables.get('edges', []) if e['from'] == nid]
             + [{'dir': 'in', 'kind': e['kind'], 'other': e['from']}
                for e in tables.get('edges', []) if e['to'] == nid])
    n_refs = sum(1 for e in edges if e['kind'] == 'ref')

    constraints = []
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'touches' in r and nid in split(r['touches']):
                msg = r.get('statement') or r.get('why') or r.get('card') or ''
                constraints.append({'id': r['id'], 'table': tname, 'statement': msg})

    slice_root = next((p for n, _, p in slices if n == prov.get(nid)), Path('.'))
    bpath = slice_root / 'bodies' / f"{nid}.md"
    body = bpath.read_text().strip() if bpath.exists() else ''

    if args.toon:
        body_ptr = f"bodies/{nid}.md ({len(body.splitlines())} lines)" if body else '(none)'
        print(emit.toon(
            {'node': nid, 'table': table, 'slice': prov.get(nid), 'state': st,
             'edges': len(edges), 'refs': n_refs, 'constraints': len(constraints),
             'body': body_ptr},
            {'attrs': (['key', 'value'], attrs),
             'edges': (['dir', 'kind', 'other'], edges),
             'constraints': (['id', 'table', 'statement'], constraints)}))
    else:
        print(f"# {nid}   ({table}, slice={prov.get(nid)}, state={st})   "
              f"{len(edges)} edges, {len(constraints)} constraints, {n_refs} refs")
        for a in attrs:
            print(f"  {a['key']}: {a['value']}")

        print(f"\nedges (blast radius): {len(edges)}")
        for e in edges:
            arrow = '->' if e['dir'] == 'out' else '<-'
            print(f"  {arrow} [{e['kind']}] {e['other']}")
        if not edges:
            print("  0 - nothing references this node and it references nothing")

        print(f"\nconstraints that touch it: {len(constraints)}")
        for c in constraints:
            print(f"  {c['id']} ({c['table']}): {c['statement']}")
        if not constraints:
            print("  0 - no invariant or decision touches this node")

        if body:
            print(f"\nbody ({bpath.name}):")
            print(emit.clip(body, len(body.splitlines()) if args.full else BODY_LINES,
                            f"full: read {bpath} or pass --full"))
        else:
            print(f"\nbody: 0 - no bodies/{nid}.md")

    slice_args = ' '.join(args.positional[1:]) or '.'
    if st == 'explore':
        emit.nxt(f"decide: keep it (set state:canon + point its ref at code) or drop it "
                 f"(state:dropped + write the why); then check {slice_args} --code-root <code>",
                 toon=args.toon)
    elif st == 'dropped':
        emit.nxt("dropped (a rejected record) - revive with state:explore, else leave it as "
                 "institutional memory", toon=args.toon)
    else:
        emit.nxt(f"edit the graph, then: check {slice_args} --code-root <code>", toon=args.toon)


if __name__ == '__main__':
    main()
