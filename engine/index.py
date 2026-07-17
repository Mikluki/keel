#!/usr/bin/env python3
"""index: derive the repo-wide toons/ roll-up and enforce the slug<->anchor invariant.

Walks <repo>/toons/<slug>/, reads each container's primary anchor and node health
(planned / implemented / drifted vs the code), and writes the DERIVED _index.toon board -
a repo-wide health view that cannot drift because nothing hand-writes it. In the same pass
it checks the naming invariant `slug == flatten(refs.logic)` with collision handling: a dir
named differently from its anchor, or two anchors that flatten to the same undisambiguable
slug (dec 1), fail the gate (exit 1).

Reads/writes: reads every toons/<slug>/*.graph.toon (+ resolves their `ref` edges against
--code-root via ripgrep); writes <repo>/toons/_index.toon unless --check.

    python index.py                     # discover toons/ from cwd, refresh _index.toon
    python index.py toons              # point at a toons dir (or its repo root) explicitly
    python index.py --toon              # structured body for an agent
    python index.py --check             # validate the invariant only; write nothing
"""
import sys
from pathlib import Path

import emit
import containers
from render import load_union
from status import classify


def main():
    raw = sys.argv[1:]
    write = '--check' not in raw
    args = emit.parse([a for a in raw if a != '--check'], cmd='index')

    toons = _locate_toons(args.positional)
    if toons is None:
        emit.die('NO_TOONS', 'no toons/ dir found (run inside a repo that has one, or pass its path)',
                 exit_code=3)
    repo_root = args.root or toons.parent

    dirs = containers.iter_containers(toons)
    anchors = {d.name: containers.container_anchor(d) for d in dirs}
    expected = containers.expected_slugs(anchors)

    rows, violations = [], []
    totals = {'nodes': 0, 'planned': 0, 'impl': 0, 'drifted': 0, 'explore': 0, 'dropped': 0}
    for d in dirs:
        impl, planned, drifted, explore, dropped = classify(
            load_union(containers.graph_slices(d))[1], repo_root)
        nodes = len(impl) + len(planned) + len(drifted) + len(explore) + len(dropped)
        totals['nodes'] += nodes
        totals['planned'] += len(planned)
        totals['impl'] += len(impl)
        totals['drifted'] += len(drifted)
        totals['explore'] += len(explore)
        totals['dropped'] += len(dropped)

        exp_slug, note = expected[d.name]
        if note == 'NO_ANCHOR':
            violations.append(f"{d.name}: no refs.logic anchor in any graph slice")
        elif note == 'COLLISION':
            violations.append(f"{d.name}: anchor '{anchors[d.name]}' collides - "
                              f"two anchors flatten to '{exp_slug}' (disambiguate exts or split the concept)")
        elif d.name != exp_slug:
            violations.append(f"{d.name}: slug != flatten(anchor) - expected '{exp_slug}' "
                              f"from anchor '{anchors[d.name]}'")

        rows.append({'slug': d.name, 'anchor': anchors[d.name] or '(none)', 'nodes': nodes,
                     'planned': len(planned), 'impl': len(impl), 'drifted': len(drifted),
                     'explore': len(explore), 'dropped': len(dropped)})

    body = emit.toon(
        {'generated': 'DERIVED roll-up - do not hand-edit', 'root': repo_root,
         'containers': len(dirs), 'nodes': totals['nodes'], 'planned': totals['planned'],
         'impl': totals['impl'], 'drifted': totals['drifted'],
         'explore': totals['explore'], 'dropped': totals['dropped'], 'violations': len(violations)},
        {'index': (['slug', 'anchor', 'nodes', 'planned', 'impl', 'drifted', 'explore', 'dropped'],
                   rows)})

    if args.toon:
        print(body)
    else:
        print(f"containers  {len(dirs)}   root={repo_root}")
        print(f"nodes       {totals['nodes']}  ({totals['impl']} impl / "
              f"{totals['planned']} planned / {totals['drifted']} drifted / "
              f"{totals['explore']} explore / {totals['dropped']} dropped)\n")
        for r in rows:
            print(f"  {r['slug']:26} {r['impl']:>3}i {r['planned']:>3}p {r['drifted']:>3}d "
                  f"{r['explore']:>3}e {r['dropped']:>3}x   {r['anchor']}")
        if not dirs:
            print("  0 containers - no toons/<slug>/ yet")

    index_path = Path(toons) / containers.INDEX_FILE
    if write:
        index_path.write_text(body + '\n')
        print(f"wrote {index_path}", file=sys.stderr)

    if violations:
        print(f"\n{len(violations)} slug<->anchor violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  ! {v}", file=sys.stderr)
        emit.nxt("rename each container dir to flatten(refs.logic), or fix its refs.logic anchor",
                 toon=args.toon)
        sys.exit(1)
    emit.nxt("keel check <slug> to open a container's loop, or keel find <path> to "
             "reverse-look-up a source file", toon=args.toon, guide=True)


def _locate_toons(positional):
    """The toons dir from an optional positional (a toons dir OR its repo root), else discovered."""
    if not positional:
        return containers.find_toons_root()
    p = Path(positional[0])
    if p.name == containers.TOONS_DIR and p.is_dir():
        return p
    if (p / containers.TOONS_DIR).is_dir():
        return p / containers.TOONS_DIR
    return None


if __name__ == '__main__':
    main()
