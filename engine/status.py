#!/usr/bin/env python3
"""status: a divergence dashboard for a spec-graph.

Where lint/refs are pass/fail gates, status aggregates health into one diagnostic
view: implemented vs planned vs DRIFTED nodes (graph<->code), rule failures, orphan
nodes, and the unbuilt cross-slice seams with who depends on each. Domain-agnostic -
reads only nodes / edges / rules / ref edges.

    python status.py [slices...] [--code-root R]
    python status.py .toons/<slug> --code-root ../my-crate --toon     # structured body for an agent
"""
import sys

import emit
from refs import resolve
from render import SYSTEM_TABLES, load_union, resolve_paths, split, state_of


def node_rows(tables):
    for name, rows in tables.items():
        if name not in SYSTEM_TABLES:
            yield from rows


def classify(tables, root):
    """Partition node ids by declared state, then classify the CANON lane by realization.

    Returns (implemented, planned, drifted, explore, dropped). Realization
    (planned/implemented/drifted vs the code root) is computed over CANON nodes only - that
    is health; explore and dropped are the declared lanes, returned as id lists. planned =
    no `ref` edge yet; implemented = every ref resolves; drifted = at least one ref points at
    vanished code (items are (id, [(target, status), ...]) for the non-OK targets). Only
    canon refs are resolved - ripgrep is the costly step. Shared with index.py so the
    dashboard and the roll-up agree on what these words mean.
    """
    by_state = {'canon': [], 'explore': [], 'dropped': []}
    for r in node_rows(tables):
        if 'id' in r:
            by_state[state_of(r)].append(r['id'])
    canon = set(by_state['canon'])

    ref_by = {}
    for e in tables.get('edges', []):
        if e['kind'] == 'ref' and e['from'] in canon:
            ref_by.setdefault(e['from'], []).append(e['to'])
    status_of = {t: resolve(t, root)[0] for ts in ref_by.values() for t in ts}

    implemented, planned, drifted = [], [], []
    for nid in sorted(canon):
        targets = ref_by.get(nid)
        if not targets:
            planned.append(nid)
        elif all(status_of[t] == 'OK' for t in targets):
            implemented.append(nid)
        else:
            drifted.append((nid, [(t, status_of[t]) for t in targets if status_of[t] != 'OK']))
    return (implemented, planned, drifted,
            sorted(set(by_state['explore'])), sorted(set(by_state['dropped'])))


def main():
    args = emit.parse(sys.argv[1:], cmd='status')
    paths = resolve_paths(args.positional)
    slices, tables, _ = load_union(paths)
    root = emit.default_root(args.root, paths)

    ids = {r['id'] for r in node_rows(tables) if 'id' in r}
    edges = tables.get('edges', [])
    implemented, planned, drifted, explore, dropped = classify(tables, root)

    incident = {x for e in edges for x in (e['from'], e['to'])}
    touched, active = set(), set()
    for r in node_rows(tables):
        if r.get('touches', '').strip():
            active.add(r.get('id'))
            touched |= set(split(r['touches']))
    noncanon = set(explore) | set(dropped)   # a non-canon node being unwired is expected
    orphans = sorted(ids - incident - touched - active - noncanon)

    seen, dups = set(), set()
    for r in node_rows(tables):
        if r.get('id') in seen:
            dups.add(r['id'])
        seen.add(r.get('id'))

    rule_fail = []
    for rule in tables.get('rules', []):
        if rule['kind'] == 'needs-edge':
            tbl, ek = rule['a'], rule['b']
            have = {x for e in edges if e['kind'] == ek for x in (e['from'], e['to'])}
            rule_fail += [f"{tbl} '{r['id']}' missing '{ek}' edge"
                          for r in tables.get(tbl, []) if r['id'] not in have]

    valid, seam = ids | set(tables), {}
    for e in edges:
        if e['kind'] == 'ref':
            continue
        for a, b in ((e['from'], e['to']), (e['to'], e['from'])):
            if a not in valid:
                seam.setdefault(a, set()).add(b)
    for r in node_rows(tables):
        for tok in split(r.get('touches', '')):
            if tok not in valid:
                seam.setdefault(tok, set()).add(r.get('id'))

    names = ', '.join(n for n, _, _ in slices)
    drift_rows = [{'node': nid, 'to': t, 'status': s} for nid, probs in drifted for t, s in probs]
    seam_rows = [{'seam': s, 'dependents': ' '.join(sorted(seam[s]))} for s in sorted(seam)]

    if args.toon:
        print(emit.toon(
            {'slices': names, 'slices_loaded': len(slices), 'nodes': len(ids), 'root': root,
             'canon': len(implemented) + len(planned) + len(drifted),
             'explore': len(explore), 'dropped': len(dropped),
             'implemented': len(implemented), 'planned': len(planned), 'drifted': len(drifted),
             'rules': len(tables.get('rules', [])), 'rules_failing': len(rule_fail),
             'orphans': len(orphans), 'duplicate_ids': len(dups), 'seams': len(seam)},
            {'planned': (['id'], [{'id': n} for n in planned]),
             'drifted': (['node', 'to', 'status'], drift_rows),
             'explore': (['id'], [{'id': n} for n in explore]),
             'dropped': (['id'], [{'id': n} for n in dropped]),
             'rule_fail': (['detail'], [{'detail': f} for f in rule_fail]),
             'orphans': (['id'], [{'id': o} for o in orphans]),
             'duplicate_ids': (['id'], [{'id': d} for d in sorted(dups)]),
             'seams': (['seam', 'dependents'], seam_rows)}))
    else:
        print(f"slices   {names}  ({len(slices)} loaded)")
        print(f"nodes    {len(ids)}\n")
        print("LIFECYCLE (declared state):")
        print(f"  canon        {len(implemented) + len(planned) + len(drifted)}   (accepted design)")
        print(f"  explore      {len(explore)}"
              + (f"   ({emit.trunc_list(explore, 8, full=args.full)})" if explore
                 else "   - none under evaluation"))
        print(f"  dropped      {len(dropped)}"
              + (f"   ({emit.trunc_list(dropped, 8, full=args.full)})" if dropped
                 else "   - none rejected"))
        print(f"\nCODE (canon graph -> code, root={root}):")
        print(f"  implemented  {len(implemented)}")
        print(f"  planned      {len(planned)}   (no ref edge yet)")
        print(f"  DRIFTED      {len(drifted)}   (ref points at vanished code)")
        for nid, probs in drifted:
            for t, s in probs:
                print(f"     ! {nid} -> {t}  [{s}]")
        print("\nCONSISTENCY:")
        print(f"  rules        {len(tables.get('rules', []))} declared, {len(rule_fail)} failing")
        for f in rule_fail:
            print(f"     ! {f}")
        print(f"  orphans      {len(orphans)}"
              + (f"  ({emit.trunc_list(orphans, 8, full=args.full)})" if orphans else ""))
        print(f"  duplicate id {len(dups)}" + (f"  ({', '.join(sorted(dups))})" if dups else ""))
        print(f"\nSEAMS (referenced, not loaded - the unbuilt slices): {len(seam)}")
        for s in sorted(seam):
            print(f"  {s:16} <- {emit.trunc_list(sorted(seam[s]), 6, full=args.full)}")
        if not seam:
            print("  0 - every referenced node is loaded")

    if planned:
        emit.nxt(f"pack {planned[0]} {names_for(args)} - implement a planned canon node",
                 toon=args.toon)
    elif drifted:
        emit.nxt(f"pack {drifted[0][0]} {names_for(args)} - reconcile the drifted ref",
                 toon=args.toon)
    elif explore:
        emit.nxt(f"pack {explore[0]} {names_for(args)} - decide: keep (state:canon) "
                 f"or drop (state:dropped)", toon=args.toon)
    else:
        emit.nxt(f"render {names_for(args)} - all canon nodes implemented; refresh the view",
                 toon=args.toon)


def names_for(args):
    return ' '.join(args.positional) or '.'


if __name__ == '__main__':
    main()
