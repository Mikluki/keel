#!/usr/bin/env python3
"""context: the 1-hop context of a THING - a graph node, or a code coordinate.

<node>: the node's attributes + bodies/ prose + every edge touching it (in & out =
the blast radius) + every invariant/decision that `touches` it + its code refs.
~20 lines instead of the whole spec - this is the loop's PICK step. With --code-root
each ref edge also RESOLVES inline (status + file:line + the live matched line), so
a ref'd constant shows its current value without the graph ever storing it.
Resolution runs ONLY when --code-root is passed - no root inference here, a guessed
root would decorate every ref with false MISSING noise.

<code coordinate>: the REVERSE question - which graph nodes pin this code, with their
cards. Ask before editing code the graph may have opinions about. A coordinate is an
exact ref target (`py/pkg/rigor.py#BOOT_REPS`), a /-boundary suffix of one
(`rigor.py#BOOT_REPS`), or a bare symbol (`BOOT_REPS`). Anything that is neither a
node id nor a matching ref target dies loud naming both.

    python context.py <node-id> [slices...]
    python context.py <node> .toons/<slug> --code-root ../crate   # refs resolve inline
    python context.py src/auth.rs#AuthService .toons/<slug>       # code -> graph
    python context.py <node> .toons/<slug> --brief     # truncate the prose body (full by default)
"""
import sys
from pathlib import Path

import containers
import emit
from drift import evidence_str, resolve
from render import SYSTEM_TABLES, load_union, resolve_paths, split, state_of

BODY_LINES = 12          # prose body truncated past this under --brief; full by default


def ref_matches(tables, query):
    """The ref edges whose CODE target the query names: exact, a /-boundary suffix
    (`rigor.py#X` hits `py/pkg/rigor.py#X`), or a bare symbol (`X` hits `...#X`)."""
    hits = []
    for e in tables.get('edges', []):
        if e['kind'] != 'ref':
            continue
        t = e['to']
        if (t == query or t.endswith('/' + query)
                or ('/' not in query and '#' not in query
                    and '#' in t and t.rsplit('#', 1)[1] == query)):
            hits.append(e)
    return hits


def code_mode(args, query, tables, slices):
    """code coordinate -> the graph nodes that pin it (+ resolution when rooted)."""
    hits = ref_matches(tables, query)
    if not hits:
        emit.die('NOT_FOUND', f"'{query}' is neither a node id nor a ref target in the "
                 "loaded union", exit_code=3)
    node_of = {}
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'id' in r:
                node_of.setdefault(r['id'], (tname, r))
    ref_rows = []
    for e in hits:
        tname, r = node_of.get(e['from'], ('?', {}))
        ref_rows.append({'id': e['from'], 'table': tname,
                         'state': state_of(r) if r else '?',
                         'card': r.get('card', ''), 'target': e['to']})
    targets = sorted({e['to'] for e in hits})
    code_rows = []
    if args.root is not None:
        for t in targets:
            status, ev = resolve(t, args.root)
            code_rows.append({'status': status, 'target': t,
                              'evidence': evidence_str(status, ev, args.full)})

    names = ', '.join(n for n, _, _ in slices)
    if args.toon:
        tbls = {'nodes': (['id', 'table', 'state', 'card', 'target'], ref_rows)}
        if args.root is not None:
            tbls['code'] = (['status', 'target', 'evidence'], code_rows)
        print(emit.toon({'query': query, 'slices': names, 'nodes': len(ref_rows),
                         'targets': len(targets)}, tbls))
    else:
        print(f"# {query}   (code coordinate)   {len(ref_rows)} referring node(s), "
              f"{len(targets)} target(s)")
        for n in ref_rows:
            print(f"  {n['id']}  ({n['table']}, {n['state']}): {n['card']}")
            if n['target'] != query:
                print(f"      ref: {n['target']}")
        if code_rows:
            print("\ncode:")
            for c in code_rows:
                tail = f"  [{c['evidence']}]" if c['evidence'] else ''
                print(f"  {c['status']:12} {c['target']}{tail}")

    slice_str = ' '.join(containers.display_arg(a) for a in args.positional[1:]) or '.'
    emit.nxt(f"keel context {ref_rows[0]['id']} {slice_str} - the pinning node's full "
             "1-hop context", toon=args.toon)


def main():
    args = emit.parse(sys.argv[1:], cmd='context')
    if not args.positional:
        emit.die('USAGE', 'context needs a node id or code coordinate: '
                 'context <node|file#symbol> [slices...]')
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
        code_mode(args, nid, tables, slices)   # dies loud if it is no coordinate either
        return
    st = state_of(row)

    attrs = [{'key': k, 'value': v} for k, v in row.items() if k != 'id']
    edges = ([{'dir': 'out', 'kind': e['kind'], 'other': e['to']}
              for e in tables.get('edges', []) if e['from'] == nid]
             + [{'dir': 'in', 'kind': e['kind'], 'other': e['from']}
                for e in tables.get('edges', []) if e['to'] == nid])
    n_refs = sum(1 for e in edges if e['kind'] == 'ref')

    res = {}                     # explicit --code-root only (see module docstring)
    if args.root is not None:
        res = {e['other']: resolve(e['other'], args.root)
               for e in edges if e['kind'] == 'ref' and e['dir'] == 'out'}

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
        tbls = {'attrs': (['key', 'value'], attrs),
                'edges': (['dir', 'kind', 'other'], edges),
                'constraints': (['id', 'table', 'statement'], constraints)}
        if args.root is not None:
            tbls['code'] = (['status', 'target', 'evidence'],
                            [{'status': s, 'target': t,
                              'evidence': evidence_str(s, ev, args.full)}
                             for t, (s, ev) in res.items()])
        print(emit.toon(
            {'node': nid, 'table': table, 'slice': prov.get(nid), 'state': st,
             'edges': len(edges), 'refs': n_refs, 'constraints': len(constraints),
             'body': body_ptr}, tbls))
    else:
        print(f"# {nid}   ({table}, slice={prov.get(nid)}, state={st})   "
              f"{len(edges)} edges, {len(constraints)} constraints, {n_refs} refs")
        for a in attrs:
            print(f"  {a['key']}: {a['value']}")

        print(f"\nedges (blast radius): {len(edges)}")
        for e in edges:
            arrow = '->' if e['dir'] == 'out' else '<-'
            line = f"  {arrow} [{e['kind']}] {e['other']}"
            if e['other'] in res:
                s, ev = res[e['other']]
                evs = evidence_str(s, ev, args.full)
                line += f"   {s}" + (f" [{evs}]" if evs else '')
            print(line)
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

    slice_args = ' '.join(containers.display_arg(a) for a in args.positional[1:]) or '.'
    if st == 'explore':
        emit.nxt(f"decide: keep it (set state:canon + point its ref at code) or drop it "
                 f"(state:dropped + write the why); then keel check {slice_args} "
                 "--code-root <code>", toon=args.toon)
    elif st == 'dropped':
        emit.nxt("dropped (a rejected record) - revive with state:explore, else leave it as "
                 "institutional memory", toon=args.toon)
    else:
        emit.nxt(f"edit the graph, then: keel check {slice_args} --code-root <code>",
                 toon=args.toon)


if __name__ == '__main__':
    main()
