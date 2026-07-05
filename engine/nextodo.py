#!/usr/bin/env python3
"""nextodo: the ranked worklist - what to do next, derived from the graph.

Where status DIAGNOSES divergence, nextodo answers one question: what is worth doing
right now. Every lane is DERIVED from edges + ref resolution - no plan files, no
status columns, nothing new to author or re-sync:

    fix      drifted canon refs - the graph is lying; reconcile before trusting it
    ready    planned canon whose prerequisites are ALL implemented, ranked by leverage
             (frees = blocked nodes it is the last obstacle for) and grouped into
             LANES - a lane shares an edge or a constraint, so nodes in DIFFERENT
             lanes are safe to hand to parallel agents
    decide   explore nodes awaiting keep/drop
    blocked  planned canon waiting on unbuilt prerequisites, closest-to-ready first

A prerequisite is a directed out-edge to another node (the same dependency semantics
the lint state-gate uses): `ref` edges and kinds declared `undirected` never order
work; an edge to an UNLOADED node blocks (its state is unknown - load that slice).

    python nextodo.py [slices...] --code-root R          the whole worklist
    python nextodo.py <goal> [slices...] --code-root R   only what stands between you and <goal>
    python nextodo.py ... --brief                        agent-lean: top ready + counts
"""
import sys
from pathlib import Path

import emit
from render import SYSTEM_TABLES, load_union, resolve_paths, split
from status import classify, node_rows

READY_BRIEF = 3      # ready rows an agent sees under --brief (the human default is full)
BLOCKED_BRIEF = 5


def main():
    args = emit.parse(sys.argv[1:], cmd='nextodo')
    goal, slice_args = None, []
    for a in args.positional:            # the one non-path positional is the goal node
        if Path(a).exists():
            slice_args.append(a)
        elif goal is None:
            goal = a
        else:
            emit.die('USAGE', f"two non-path args ({goal!r}, {a!r}) - "
                     "nextodo takes at most one goal node")
    paths = resolve_paths(slice_args)
    slices, tables, _ = load_union(paths)
    root = emit.default_root(args.root, paths)
    implemented, planned, drifted, explore, dropped = classify(tables, root)
    ids = {r['id'] for r in node_rows(tables) if 'id' in r}
    table_of = {}                        # a node's home table - the human's "what kind" cue
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'id' in r:
                table_of.setdefault(r['id'], tname)

    # prerequisites: directed non-ref out-edges. A table-name endpoint is a category,
    # not buildable work; an endpoint resolving to neither is an unloaded seam node.
    undirected = {r['a'] for r in tables.get('rules', []) if r['kind'] == 'undirected'}
    prereq = {}
    for e in tables.get('edges', []):
        if e['kind'] == 'ref' or e['kind'] in undirected or e['to'] in tables:
            continue
        if e['from'] in ids:
            prereq.setdefault(e['from'], set()).add(e['to'])

    # goal mode: restrict every lane to the goal's transitive prerequisite cone
    scope = ids
    if goal is not None:
        if goal not in ids:
            emit.die('NODE_NOT_FOUND', f"'{goal}' is neither an existing path nor a node "
                     "id in the loaded union", exit_code=3)
        scope, queue = {goal}, [goal]
        while queue:
            for t in prereq.get(queue.pop(), ()):
                if t not in scope:
                    scope.add(t)
                    queue.append(t)

    drift_ids = {n for n, _ in drifted}
    # dropped is rejected design - it cannot block work (lint flags such an edge itself)
    unbuilt = (set(planned) | drift_ids | set(explore)) - set(dropped)
    planned_s = [n for n in planned if n in scope]
    explore_s = [n for n in explore if n in scope]
    fix = [(n, probs) for n, probs in drifted if n in scope]

    def unbuilt_prereqs(n):
        out = []
        for t in sorted(prereq.get(n, ())):
            if t in unbuilt:
                out.append(t)
            elif t not in ids:
                out.append(f"{t} (not loaded)")
        return out

    missing = {n: unbuilt_prereqs(n) for n in planned_s}
    ready = [n for n in planned_s if not missing[n]]
    blocked = sorted((n for n in planned_s if missing[n]),
                     key=lambda b: (len(missing[b]), b))          # closest-to-ready first
    unblocks = {r: [b for b in blocked if r in missing[b]] for r in ready}
    frees = {r: [b for b in blocked if missing[b] == [r]] for r in ready}
    rank = sorted(ready, key=lambda r: (-len(frees[r]), -len(unblocks[r]), r))

    # lanes: ready nodes coupled by a direct edge or a shared `touches` constraint work
    # the same ground; DIFFERENT lanes are safe to hand to parallel agents
    readyset = set(rank)
    adj = {r: set() for r in rank}
    for e in tables.get('edges', []):
        if (e['kind'] != 'ref' and e['from'] in readyset and e['to'] in readyset
                and e['from'] != e['to']):
            adj[e['from']].add(e['to'])
            adj[e['to']].add(e['from'])
    for r in node_rows(tables):
        touched = [t for t in split(r.get('touches', '')) if t in readyset]
        for a, b in zip(touched, touched[1:]):    # consecutive pairs suffice to connect
            adj[a].add(b)
            adj[b].add(a)
    lane_of, n_lanes = {}, 0
    for r in rank:                                # rank order -> lane 1 holds the top pick
        if r in lane_of:
            continue
        n_lanes += 1
        stack = [r]
        while stack:
            x = stack.pop()
            if x not in lane_of:
                lane_of[x] = n_lanes
                stack.extend(adj[x])

    gstate = ''
    if goal is not None:
        if goal in drift_ids:
            gstate = 'DRIFTED - reconcile its ref first'
        elif goal in implemented:
            gstate = 'implemented - nothing stands between you and it'
        elif goal in explore:
            gstate = 'explore - decide keep/drop first'
        elif goal in dropped:
            gstate = 'dropped - a rejected design; revive with state:explore first'
        elif goal in readyset:
            gstate = 'planned and READY - no unbuilt prerequisites'
        else:
            gstate = f"planned, waiting on {len(missing.get(goal, []))} unbuilt"

    names = ', '.join(n for n, _, _ in slices)
    slice_str = ' '.join(slice_args) or '.'

    def leverage(r):
        parts = []
        if frees[r]:
            parts.append(f"frees {len(frees[r])}: "
                         + emit.trunc_list(frees[r], 4, full=args.full, hint='drop --brief'))
        if len(unblocks[r]) > len(frees[r]):
            parts.append(f"unblocks {len(unblocks[r])}")
        return ('  ' + '  '.join(parts)) if parts else ''

    if args.toon:
        scalars = {'slices': names, 'root': root, 'fix': len(fix), 'ready': len(ready),
                   'lanes': n_lanes, 'decide': len(explore_s), 'blocked': len(blocked),
                   'implemented': len(implemented), 'planned': len(planned_s)}
        if goal is not None:
            scalars = {'goal': goal, 'goal_state': gstate, **scalars}
        shown = rank if args.full else rank[:READY_BRIEF]
        print(emit.toon(scalars, {
            'fix': (['node', 'to', 'status'],
                    [{'node': n, 'to': t, 'status': s} for n, probs in fix for t, s in probs]),
            'ready': (['id', 'table', 'lane', 'frees', 'unblocks', 'frees_ids'],
                      [{'id': r, 'table': table_of.get(r, ''), 'lane': lane_of[r],
                        'frees': len(frees[r]), 'unblocks': len(unblocks[r]),
                        'frees_ids': ' '.join(frees[r])}
                       for r in shown]),
            'decide': (['id'], [{'id': n} for n in explore_s]),
            'blocked': (['id', 'missing'],
                        [{'id': b, 'missing': ' '.join(missing[b])} for b in blocked])}))
    else:
        print(f"nextodo [{names}]  root={root}")
        if goal is not None:
            print(f"goal {goal}: {gstate}")
        print(f"fix {len(fix)} | ready {len(ready)} in {n_lanes} lanes | "
              f"decide {len(explore_s)} | blocked {len(blocked)}\n")

        if fix:
            print(f"FIX {len(fix)} - drifted canon refs; the graph is lying, reconcile first:")
            for n, probs in fix:
                for t, s in probs:
                    print(f"  ! {n} -> {t}  [{s}]")
        else:
            print("FIX 0 - no drifted canon refs")

        if rank:
            print(f"\nREADY {len(rank)} in {n_lanes} lanes - all prerequisites implemented, "
                  "ranked by leverage; same lane = shared blast radius, do not parallelize:")
            shown_r = rank if args.full else rank[:READY_BRIEF]
            for r in shown_r:
                print(f"  ln {lane_of[r]:>2}  {r:<24}{table_of.get(r, ''):<12}"
                      f"{leverage(r)}".rstrip())
            if len(rank) > len(shown_r):
                print(f"  (+{len(rank) - len(shown_r)} more; drop --brief)")
        elif blocked:
            print("\nREADY 0 - nothing buildable; every planned node waits (see BLOCKED)")
        else:
            print("\nREADY 0 - nothing planned" + (" in this cone" if goal else ""))

        if explore_s:
            print(f"\nDECIDE {len(explore_s)} - explore awaiting keep/drop: "
                  + emit.trunc_list(explore_s, 8, full=args.full, hint='drop --brief'))
        else:
            print("\nDECIDE 0 - no explore nodes awaiting a decision")

        if blocked:
            print(f"\nBLOCKED {len(blocked)} - waiting on unbuilt prerequisites, "
                  "closest-to-ready first:")
            shown_b = blocked if args.full else blocked[:BLOCKED_BRIEF]
            for b in shown_b:
                print(f"  {b:<24}<- {', '.join(missing[b])}")
            if len(blocked) > len(shown_b):
                print(f"  (+{len(blocked) - len(shown_b)} more; drop --brief)")
        else:
            print("\nBLOCKED 0 - nothing waits on unbuilt work")

    if fix:
        emit.nxt(f"pack {fix[0][0]} {slice_str} - reconcile the drifted ref, then re-run "
                 "nextodo", toon=args.toon)
    elif rank:
        gain = f" (frees {len(frees[rank[0]])})" if frees[rank[0]] else ''
        emit.nxt(f"pack {rank[0]} {slice_str} - top of the worklist{gain}", toon=args.toon)
    elif explore_s:
        emit.nxt(f"pack {explore_s[0]} {slice_str} - decide: keep (state:canon) or drop "
                 "(state:dropped)", toon=args.toon)
    elif blocked:
        emit.nxt("every planned node waits on another - a dependency cycle or an unloaded "
                 "slice; inspect BLOCKED", toon=args.toon)
    else:
        emit.nxt(f"render {slice_str} - nothing to do; all canon implemented", toon=args.toon)


if __name__ == '__main__':
    main()
