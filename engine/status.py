#!/usr/bin/env python3
"""status: a divergence dashboard for a spec-graph.

Where lint/drift are pass/fail gates, status aggregates health into one diagnostic
view: implemented vs planned vs DRIFTED nodes (graph<->code), rule failures, orphan
nodes, and the unbuilt cross-slice seams with who depends on each. Domain-agnostic -
reads only nodes / edges / rules / ref edges.

    python status.py [slices...] [--code-root R]
    python status.py toons/<slug> --code-root ../my-crate --toon     # structured body for an agent
"""
import sys

import containers
import emit
from drift import resolve
from render import (CELL_HARD_MAX, CELL_MAX, SYSTEM_TABLES, cell_errors,
                    cell_warnings, leaked_numbers, load_union, resolve_paths, split,
                    state_of, weight_summary)


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
    slices, tables, prov = load_union(paths)
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

    long_cells = cell_warnings(tables, slices, prov)   # soft: prose cells grown past a one-liner
    hard_cells = cell_errors(tables, slices, prov)     # hard: canon cells grown into a body (gates check)
    leaks = leaked_numbers(tables, slices, prov)       # soft: measured numbers stranded in prose
    weight = weight_summary(tables, slices, prov)      # the WEIGHT axis rolled up (single-sourced w/ index)

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
             'orphans': len(orphans), 'duplicate_ids': len(dups),
             'long_cells': len(long_cells), 'cells_over_hard': len(hard_cells),
             'leaked_numbers': len(leaks), 'prose_chars': weight['prose_chars'],
             'split_brain': weight['split_brain'], 'seams': len(seam)},
            {'planned': (['id'], [{'id': n} for n in planned]),
             'long_cells': (['id', 'col', 'chars', 'has_body'],
                            [{'id': w['id'], 'col': w['col'], 'chars': w['len'],
                              'has_body': w['has_body']}
                             for w in long_cells]),
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
        # two axes: CONSISTENCY is wiring (structure), WEIGHT is prose rot - kept apart so a
        # graph green on wiring is never read as green overall (see render.weight_summary).
        print("\nCONSISTENCY (wiring):")
        print(f"  rules        {len(tables.get('rules', []))} declared, {len(rule_fail)} failing")
        for f in rule_fail:
            print(f"     ! {f}")
        print(f"  orphans      {len(orphans)}"
              + (f"  ({emit.trunc_list(orphans, 8, full=args.full)})" if orphans else ""))
        print(f"  duplicate id {len(dups)}" + (f"  ({', '.join(sorted(dups))})" if dups else ""))
        print("\nWEIGHT (prose rot):")
        print(f"  prose chars  {weight['prose_chars']}")
        long_labels = [f"{w['id']}:{w['col']}" for w in long_cells]
        print(f"  over soft    {len(long_cells)}"
              + (f"  (>{CELL_MAX} chars: "
                 f"{emit.trunc_list(long_labels, 8, full=args.full)})"
                 if long_cells else ""))
        hard_labels = [f"{w['id']}:{w['col']}" for w in hard_cells]
        print(f"  over hard    {len(hard_cells)}"
              + (f"  (>{CELL_HARD_MAX} chars, gates check: "
                 f"{emit.trunc_list(hard_labels, 8, full=args.full)})"
                 if hard_cells else ""))
        leak_labels = [f"{w['id']}:{w['col']}" for w in leaks]
        print(f"  leaked nums  {len(leaks)}"
              + (f"  (no drift-checked home: "
                 f"{emit.trunc_list(leak_labels, 8, full=args.full)})"
                 if leaks else ""))
        split_labels = [f"{w['id']}:{w['col']}" for w in long_cells if w['has_body']]
        print(f"  split brain  {weight['split_brain']}"
              + (f"  (long cell + body, rationale in two places: "
                 f"{emit.trunc_list(split_labels, 8, full=args.full)})"
                 if split_labels else ""))
        print(f"\nSEAMS (referenced, not loaded - the unbuilt slices): {len(seam)}")
        for s in sorted(seam):
            print(f"  {s:16} <- {emit.trunc_list(sorted(seam[s]), 6, full=args.full)}")
        if not seam:
            print("  0 - every referenced node is loaded")

    # verdict on BOTH axes: a wiring all-clear must never be claimed while weight is heavy.
    if drifted:                            # fix first: a lying graph poisons the worklist
        emit.nxt(f"keel context {drifted[0][0]} {names_for(args)} - reconcile the drifted ref",
                 toon=args.toon)
    elif hard_cells:                       # a canon cell grown into a body gates check - remediation
        emit.nxt(f"{len(hard_cells)} cell(s) over {CELL_HARD_MAX} chars gate check - move each to "
                 f"bodies/<id>.md and leave a one-liner, then re-run keel check", toon=args.toon)
    elif planned or explore:
        emit.nxt(f"keel todo {names_for(args)} - the ranked worklist (ready lanes, "
                 f"decisions, blockers)", toon=args.toon, guide=True)
    elif long_cells or leaks:              # wiring clean but weight heavy: name the second axis
        emit.nxt(f"wiring clean; WEIGHT: {len(long_cells)} cell(s) over {CELL_MAX} chars, "
                 f"{len(leaks)} number(s) stranded - move prose to bodies/<id>.md, numbers to "
                 f"a sidecar finding", toon=args.toon, guide=True)
    else:
        emit.nxt(f"keel render {names_for(args)} - clean on both axes; refresh the view",
                 toon=args.toon, guide=True)


def names_for(args):
    return ' '.join(containers.display_arg(a) for a in args.positional) or '.'


if __name__ == '__main__':
    main()
