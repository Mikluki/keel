#!/usr/bin/env python3
"""Generic consistency gate for ANY spec-graph (no domain knowledge).

Unions slices, then checks: ids unique; every edge endpoint and every `touches`
token resolves to a node id (or a table-name category) - else it is a cross-slice
ref, listed not failed; and any declared `rules` hold. Knows nothing about the
domain's node/edge kinds - those live in the .toon data.

    python lint.py                 # all *.graph.toon in cwd
    python lint.py a.graph.toon b.graph.toon a.views.toon
    python lint.py .toons/<slug> --toon       # structured (TOON) body for an agent
"""
import sys

import containers
import emit
from render import (CARD_MAX, STATES, SYSTEM_TABLES, card_warnings, load_union,
                    resolve_paths, split, state_of)


def node_rows(tables):
    for name, rows in tables.items():
        if name not in SYSTEM_TABLES:
            yield from rows


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='lint')
    slices, tables, prov = load_union(resolve_paths(args.positional))
    ids = {r['id'] for r in node_rows(tables) if 'id' in r}
    valid = ids | set(tables)            # a ref resolves to a node id or a table category
    errors, externals, seen = [], set(), set()
    state_by = {r['id']: state_of(r) for r in node_rows(tables) if 'id' in r}

    for r in node_rows(tables):
        if r.get('id') in seen:
            errors.append(f"duplicate id: {r['id']}")
        if 'id' in r:
            seen.add(r['id'])
        st = r.get('state')
        if st and st not in STATES:      # a typo'd state must fail loud, not silently -> canon
            errors.append(f"node '{r.get('id')}' has invalid state '{st}' "
                          f"(want one of {'/'.join(STATES)})")

    for e in tables.get('edges', []):
        if e['kind'] == 'ref':            # code refs are checked by refs.py, not node-resolution
            continue
        externals |= {x for x in (e['from'], e['to']) if x not in valid}
    for r in node_rows(tables):
        if 'touches' in r:
            externals |= {x for x in split(r['touches']) if x not in valid}

    # a canon node must not depend on an unaccepted/rejected one (you pulled the rug).
    # Kinds declared `undirected` in rules are symmetric ASSOCIATIONS, not dependencies -
    # exempt: an association with a dropped node is the record of why it was dropped,
    # and forcing an edge flip to pass the gate would bend the model to the tool.
    undirected = {r['a'] for r in tables.get('rules', []) if r['kind'] == 'undirected'}
    for e in tables.get('edges', []):
        if e['kind'] == 'ref' or e['kind'] in undirected:
            continue
        if state_by.get(e['from']) == 'canon' and state_by.get(e['to']) in ('explore', 'dropped'):
            errors.append(f"canon '{e['from']}' depends on {state_by[e['to']]} '{e['to']}' "
                          f"via '{e['kind']}' - promote it to canon, drop the dependency, "
                          f"or declare the kind undirected if it is an association")

    for rule in tables.get('rules', []):
        if rule['kind'] not in ('needs-edge', 'undirected'):
            errors.append(f"unknown rule kind '{rule['kind']}' "
                          f"(want needs-edge/undirected) - a typo'd rule gates nothing")
        if rule['kind'] == 'needs-edge':
            tbl, ek = rule['a'], rule['b']
            touched = {x for e in tables.get('edges', []) if e['kind'] == ek
                       for x in (e['from'], e['to'])}
            for r in tables.get(tbl, []):
                if state_of(r) != 'canon':      # only canon nodes must satisfy structural rules
                    continue
                if r['id'] not in touched:
                    errors.append(f"{tbl} '{r['id']}' missing a '{ek}' edge")

    names = ', '.join(n for n, _, _ in slices)
    unresolved = sorted(externals)
    n_edges = len(tables.get('edges', []))
    warnings = card_warnings(tables, slices, prov)   # soft: cards grown into prose (non-gating)

    if args.toon:
        print(emit.toon(
            {'slices': names, 'nodes': len(ids), 'edges': n_edges,
             'unresolved': len(unresolved), 'warnings': len(warnings), 'errors': len(errors)},
            {'unresolved': (['ref'], [{'ref': x} for x in unresolved]),
             'warnings': (['id', 'chars', 'has_body'],
                          [{'id': w['id'], 'chars': w['len'], 'has_body': w['has_body']}
                           for w in warnings]),
             'errors': (['detail'], [{'detail': e} for e in errors])}))
    else:
        print(f"lint [{names}]: {len(ids)} nodes, {n_edges} edges, "
              f"{len(unresolved)} unresolved, {len(warnings)} warnings, {len(errors)} errors")
        if unresolved:
            print(f"  unresolved cross-slice refs: {emit.trunc_list(unresolved, 12, full=args.full)}")
        else:
            print("  unresolved cross-slice refs: 0")
        if warnings:
            print(f"  warnings ({len(warnings)}): cards over {CARD_MAX} chars are prose, not a table row -")
            print("    card = intent; rationale -> bodies/<id>.md; measured findings -> a results sidecar "
                  "or refs.numbers data; chosen constants -> code, ref'd by symbol (file#CONST) "
                  "(a card is never drift-checked, so a stale number there passes green)")
            shown = warnings if args.full else warnings[:12]
            for w in shown:
                split_note = "  (also has a body - rationale split two ways)" if w['has_body'] else ""
                print(f"    {w['id']:24} {w['len']:>4} chars{split_note}")
            if len(warnings) > len(shown):
                print(f"    (+{len(warnings) - len(shown)} more; --full)")
        else:
            print("  warnings: 0 - every card is a one-liner")
        if errors:
            print(f"  ERRORS ({len(errors)}):")
            for er in errors:
                print(f"    x {er}")
        else:
            print("  errors: 0 - edges + touches resolve, ids unique, rules satisfied")

    slice_args = ' '.join(containers.display_arg(a) for a in args.positional) or '.'
    if errors:
        emit.nxt(f"fix the {len(errors)} error(s) above in the graph, then re-run keel check",
                 toon=args.toon)
        sys.exit(1)
    emit.nxt(f"keel refs {slice_args} --code-root <code> - now check graph<->code drift",
             toon=args.toon)


if __name__ == '__main__':
    main()
