#!/usr/bin/env python3
"""context: the 1-hop context of a THING - a graph node, a node SET, or a code coordinate.

<node>: the node's attributes + bodies/ prose + every edge touching it (in & out =
the blast radius) + every invariant/decision that `touches` it + its code refs.
~20 lines instead of the whole spec - this is the loop's PICK step. With --code-root
each ref edge also RESOLVES inline (status + file:line + the live matched line), so
a ref'd constant shows its current value without the graph ever storing it.
Resolution runs ONLY with a --code-root - typed, or supplied by the .toons slug
contract (a bare <slug> arg injects the repo root). Never inferred from a plain path:
a guessed root would decorate every ref with false MISSING noise.

<node set>: a `[table:]col=val` selector (recognized by the '=') -> the INDUCED
SUBGRAPH of every node whose column matches: the members, the edges AMONG them
(internal) vs the edges to the outside (boundary = the seams), each invariant/decision
touching the set ONCE (with which members), and the members' code refs (deduped by
target, resolved inline when rooted). This is the GROUP answer a single-node context
cannot give - `metric:tier=B` enumerates the whole tier from the graph's own column,
so a class ask ("context on B") never degrades into a hand-typed, half-complete member
list. `table:` scopes to one node table; bare `col=val` scans every table; `state=canon`
matches unset-state nodes too (unset =~ canon).

<code coordinate>: the REVERSE question - which graph nodes pin this code, with their
cards. Ask before editing code the graph may have opinions about. A coordinate is an
exact ref target (`py/pkg/rigor.py#BOOT_REPS`), a /-boundary suffix of one
(`rigor.py#BOOT_REPS`), or a bare symbol (`BOOT_REPS`). Anything that is neither a
node id, a selector, nor a matching ref target dies loud naming both.

    python context.py <node-id> [slices...]
    python context.py <node> .toons/<slug> --code-root ../crate   # refs resolve inline
    python context.py metric:tier=B .toons/<slug> --code-root ../crate   # a node SET's subgraph
    python context.py src/auth.rs#AuthService .toons/<slug>       # code -> graph
    python context.py <node> .toons/<slug> --brief     # truncate the prose body (full by default)
"""
import sys
from pathlib import Path

import containers
import emit
from drift import evidence_str, jump_of, resolve
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


def _resolved_row(target, status, ev, root, full):
    """One resolved ref as a display/toon row: status + target + jump location + evidence
    (the bare matched line for OK - the location owns the file:line prefixes)."""
    loc, snip = jump_of(target, status, ev, root)
    return {'status': status, 'target': target, 'location': loc,
            'evidence': snip if snip is not None else evidence_str(status, ev, full)}


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
            code_rows.append(_resolved_row(t, *resolve(t, args.root),
                                           args.root, args.full))

    names = ', '.join(n for n, _, _ in slices)
    if args.toon:
        tbls = {'nodes': (['id', 'table', 'state', 'card', 'target'], ref_rows)}
        if args.root is not None:
            tbls['code'] = (['status', 'target', 'location', 'evidence'], code_rows)
        print(emit.toon({'query': query, 'slices': names, 'nodes': len(ref_rows),
                         'targets': len(targets)}, tbls))
    else:
        print(f"# {query}   (code coordinate)   {len(ref_rows)} referring node(s), "
              f"{len(targets)} target(s)")
        for n in ref_rows:
            print(f"  {n['id']}  ({n['table']}, {n['state']}): {n['card']}")
            if n['target'] != query and not code_rows:   # the code block shows it otherwise
                print(f"      ref: {n['target']}")
        if code_rows:
            print("\ncode:")
            for c in code_rows:
                show = c['location'] or c['target']
                tail = f"  [{c['evidence']}]" if c['evidence'] else ''
                print(f"  {c['status']:12} {show}{tail}")

    slice_str = ' '.join(containers.display_arg(a) for a in args.positional[1:]) or '.'
    emit.nxt(f"keel context {ref_rows[0]['id']} {slice_str} - the pinning node's full "
             "1-hop context", toon=args.toon, guide=True)


def parse_selector(sel):
    """A node-set selector `[table:]col=val` -> (table|None, col, val). Recognized by the
    '=' (no node id or code coordinate carries one). `table:` scopes the match to one node
    table; a bare `col=val` scans every table. `val` may itself contain '=' (split once)."""
    lhs, val = sel.split('=', 1)
    if ':' in lhs:
        table, col = lhs.split(':', 1)
        table = table.strip() or None
    else:
        table, col = None, lhs
    return table, col.strip(), val.strip()


def _cell(row, col):
    """The value the selector matches on: the DECLARED state (unset =~ canon) for `state`,
    else the literal cell. Matching state_of keeps `state=canon` from silently dropping
    unset-canon nodes - the same incompleteness the set query exists to prevent."""
    return state_of(row) if col == 'state' else row.get(col)


def subgraph_mode(args, sel, tables, slices):
    """selector `[table:]col=val` -> the INDUCED SUBGRAPH of every matching node: the
    members, the edges among them (internal) vs to the outside (boundary = the seams), each
    constraint touching any member ONCE with which members it hits, and the members' code
    refs (deduped by target, resolved inline when rooted). The group answer a single-node
    context cannot give - enumerate + blast radius in one call, nothing double-printed."""
    table, col, val = parse_selector(sel)
    hits = []
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES or (table is not None and tname != table):
            continue
        for r in rows:
            if 'id' in r and _cell(r, col) == val:
                hits.append((tname, r))
    names = ', '.join(n for n, _, _ in slices)
    if not hits:
        scope = f"{table}:" if table else ''
        emit.die('NO_MATCH', f"no node matches {scope}{col}={val!r} in the loaded union "
                 f"({names})", exit_code=3)

    members = [{'id': r['id'], 'table': tname, 'state': state_of(r),
                'card': r.get('card', '')} for tname, r in hits]
    inset = {r['id'] for _, r in hits}

    internal, boundary, ref_edges = [], [], []
    for e in tables.get('edges', []):
        f, t, kind = e['from'], e['to'], e['kind']
        if kind == 'ref':
            if f in inset:
                ref_edges.append(e)
        elif f in inset and t in inset:
            internal.append({'kind': kind, 'from': f, 'to': t})
        elif f in inset:
            boundary.append({'dir': 'out', 'kind': kind, 'member': f, 'other': t})
        elif t in inset:
            boundary.append({'dir': 'in', 'kind': kind, 'member': t, 'other': f})

    constraints = []
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            touched = [n for n in split(r.get('touches', '')) if n in inset]
            if touched:
                msg = r.get('statement') or r.get('why') or r.get('card') or ''
                constraints.append({'id': r['id'], 'table': tname,
                                    'touches': ' '.join(touched), 'statement': msg})

    by_target = {}                        # dedupe refs by target, keep every owning member
    for e in ref_edges:
        by_target.setdefault(e['to'], []).append(e['from'])
    code_rows = []
    for target, owners in by_target.items():
        row = {'member': ' '.join(owners), 'target': target}
        if args.root is not None:
            got = _resolved_row(target, *resolve(target, args.root),
                                args.root, args.full)
            row.update({'status': got['status'], 'location': got['location'],
                        'evidence': got['evidence']})
        code_rows.append(row)

    if args.toon:
        tbls = {'members': (['id', 'table', 'state', 'card'], members),
                'internal': (['kind', 'from', 'to'], internal),
                'boundary': (['dir', 'kind', 'member', 'other'], boundary),
                'constraints': (['id', 'table', 'touches', 'statement'], constraints)}
        if args.root is not None:
            tbls['code'] = (['member', 'status', 'target', 'location', 'evidence'],
                            code_rows)
        else:
            tbls['refs'] = (['member', 'target'], code_rows)
        print(emit.toon(
            {'selector': sel, 'slices': names, 'nodes': len(members),
             'internal': len(internal), 'boundary': len(boundary),
             'constraints': len(constraints), 'refs': len(code_rows)}, tbls))
    else:
        print(f"# {sel}   (node set)   {len(members)} nodes, {len(internal)} internal / "
              f"{len(boundary)} boundary edges, {len(constraints)} constraints, "
              f"{len(code_rows)} refs")
        for m in members:
            print(f"  {m['id']}  ({m['table']}, {m['state']}): {m['card']}")

        print(f"\ninternal edges: {len(internal)}")
        for e in internal:
            print(f"  {e['from']} -[{e['kind']}]-> {e['to']}")
        if not internal:
            print("  0 - the set has no edges among its own members")

        print(f"\nboundary (seams): {len(boundary)}")
        for e in boundary:
            arrow = '->' if e['dir'] == 'out' else '<-'
            print(f"  {arrow} [{e['kind']}] {e['other']}   ({e['member']})")
        if not boundary:
            print("  0 - the set connects to nothing outside itself")

        print(f"\nconstraints that touch the set: {len(constraints)}")
        for c in constraints:
            print(f"  {c['id']} ({c['table']}) [{c['touches']}]: {c['statement']}")
        if not constraints:
            print("  0 - no invariant or decision touches any member")

        if code_rows:
            print(f"\ncode refs: {len(code_rows)}")
            for c in code_rows:
                if args.root is not None:
                    show = c['location'] or c['target']
                    tail = f"   [{c['evidence']}]" if c['evidence'] else ''
                    print(f"  {c['status']:12} {show}   ({c['member']}){tail}")
                else:
                    print(f"  {c['target']}   ({c['member']})")

    slice_str = ' '.join(containers.display_arg(a) for a in args.positional[1:]) or '.'
    emit.nxt(f"keel context <member> {slice_str} --code-root <code> to drill into one, then "
             f"edit the graph + keel check {slice_str} --code-root <code>",
             toon=args.toon, guide=True)


def main():
    args = emit.parse(sys.argv[1:], cmd='context')
    if not args.positional:
        emit.die('USAGE', 'context needs a node id or code coordinate: '
                 'context <node|file#symbol> [slices...]')
    nid, paths = args.positional[0], resolve_paths(args.positional[1:])
    slices, tables, prov = load_union(paths)

    if '=' in nid:                        # a [table:]col=val set selector (never an id/coord)
        subgraph_mode(args, nid, tables, slices)
        return

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
        res = {e['other']: _resolved_row(e['other'], *resolve(e['other'], args.root),
                                         args.root, args.full)
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
            tbls['code'] = (['status', 'target', 'location', 'evidence'],
                            list(res.values()))
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
                c = res[e['other']]
                loc = c['location'] if c['location'] != e['other'] else ''
                line += (f"   {c['status']}" + (f" {loc}" if loc else '')
                         + (f" [{c['evidence']}]" if c['evidence'] else ''))
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
                 "--code-root <code>", toon=args.toon, guide=True)
    elif st == 'dropped':
        emit.nxt("dropped (a rejected record) - revive with state:explore, else leave it as "
                 "institutional memory", toon=args.toon, guide=True)
    else:
        emit.nxt(f"edit the graph, then: keel check {slice_args} --code-root <code>",
                 toon=args.toon, guide=True)


if __name__ == '__main__':
    main()
