#!/usr/bin/env python3
"""matrix: a derived coverage pivot - two edge kinds crossed through one pivot table.

The graph's answer to "what covers what, and where are the gaps": rows are the targets
of <row-kind> edges leaving <pivot> nodes, columns the targets of <col-kind>, each cell
the pivot node(s) joining the pair, glyphed by EVIDENCE:

    # measured     a finding row (results sidecar) touches it
    = implemented  its refs resolve         ! drifted  a ref points at vanished code
    ~ planned      no ref edge yet          x dropped  rejected     ? explore

Empty cells are the payload - a node-link view shows connectivity, only a matrix shows
absence. Rows/cols are the kinds' TARGETS: a node no pivot points at is not a row.

    python matrix.py [slices...] --code-root R
        no axes: DISCOVERY - rank candidate projections (tables carrying two directed
        edge kinds fanning to 2+ loaded nodes each), largest short side first
    python matrix.py [slices...] <pivot> "<row-kind> x <col-kind>" [group-kind] --code-root R
        render one projection; the optional group-kind clusters rows by that edge's
        target ('@table' is reserved: group by home table). Rendered FLAT, the output
        suggests the kinds that can group the rows (`groupable by: ...`) - suggest,
        never decide; a declared kind that fits badly is reported, not silently patched.

A projection that earns its keep is LOCKED as a views row -
matrix,<Title>,<pivot>,"<row-kind> x <col-kind>",<group-kind> - and `render` regenerates
it with the graph from then on (render is graph-only: its `=` means ref'd; this command
resolves refs and splits = / !).
"""
import sys
from pathlib import Path

import containers
import emit
from render import (MATRIX_AXES, MATRIX_GLYPH, SYSTEM_TABLES, build_matrix, load_union,
                    matrix_fit_lines, matrix_legend, matrix_toon_rows, resolve_paths)
from status import classify


def group_candidates(tables, row_ids):
    """Edge kinds that can GROUP a row set - out-edges only: a kind qualifies when no row
    carries it twice and its distinct targets land strictly between 1 and the covered
    rows (one group is no grouping, all singletons neither). Full coverage ranks first.
    Falls back to the reserved '@table' (group by home table) when no edge kind
    qualifies but the rows span several tables."""
    rows, fan = set(row_ids), {}
    for e in tables.get('edges', []):
        if e['from'] in rows and e['kind'] != 'ref':
            fan.setdefault(e['kind'], {}).setdefault(e['from'], []).append(e['to'])
    out = []
    for k, by in fan.items():
        if any(len(ts) > 1 for ts in by.values()):
            continue
        groups = {ts[0] for ts in by.values()}
        if 1 < len(groups) < len(by):
            out.append({'kind': k, 'covered': len(by), 'groups': len(groups)})
    out.sort(key=lambda c: (-c['covered'], c['groups'], c['kind']))
    if not out:
        home = {r['id']: n for n, trs in tables.items() if n not in SYSTEM_TABLES
                for r in trs if 'id' in r}
        spanned = {home[r] for r in row_ids if r in home}
        if 1 < len(spanned) < len(row_ids):
            out.append({'kind': '@table', 'covered': len(row_ids),
                        'groups': len(spanned)})
    return out


def discover(tables, names, slice_str, args):
    """No axes given: enumerate candidate projections. A candidate is a pivot table with
    two edge kinds whose targets are loaded nodes (2+ distinct each) and at least one
    pivot carrying both. Rank = largest short side, then most filled cells - a matrix
    that is all-empty or degenerate (one row/col) carries no contrast, so it sinks."""
    home = {r['id']: n for n, rows in tables.items() if n not in SYSTEM_TABLES
            for r in rows if 'id' in r}
    by_kind = {}                      # (table, kind) -> {pivot: set(node targets)}
    for e in tables.get('edges', []):
        t = home.get(e['from'])
        if t is not None and e['to'] in home:
            by_kind.setdefault((t, e['kind']), {}).setdefault(e['from'], set()).add(e['to'])

    fanning = {}                      # table -> [(kind, fans, all targets)] with 2+ targets
    for (t, k), fans in by_kind.items():
        targets = set().union(*fans.values())
        if len(targets) >= 2:
            fanning.setdefault(t, []).append((k, fans, targets))
    cands = []
    for t, ks in fanning.items():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                (ka, fa, ta), (kb, fb, tb) = ks[i], ks[j]
                filled = len({(x, y) for p in set(fa) & set(fb)
                              for x in fa[p] for y in fb[p]})
                if filled:
                    gcs = group_candidates(tables, sorted(ta))
                    cands.append({'pivot': t, 'axes': f"{ka} x {kb}",
                                  'rows': len(ta), 'cols': len(tb), 'filled': filled,
                                  'group': f"{gcs[0]['kind']} ({gcs[0]['groups']})"
                                           if gcs else ''})
    cands.sort(key=lambda c: (-min(c['rows'], c['cols']), -c['filled'],
                              c['pivot'], c['axes']))

    if args.toon:
        print(emit.toon({'slices': names, 'candidates': len(cands)},
                        {'candidates': (['pivot', 'axes', 'rows', 'cols', 'filled',
                                         'group'], cands)}))
    else:
        print(f"matrix candidates [{names}] - pivot tables carrying two directed edge "
              "kinds, densest first\n")
        if not cands:
            print("  0 candidates - no table has two edge kinds fanning to 2+ loaded "
                  "nodes each")
        for c in cands:
            print((f"  {c['pivot']:<14}{c['axes']:<34}"
                   f"{f'{c['rows']} x {c['cols']}, {c['filled']} filled':<22}"
                   + (f"group: {c['group']}" if c['group'] else '')).rstrip())
    if cands:
        emit.nxt(f"keel matrix {slice_str} {cands[0]['pivot']} \"{cands[0]['axes']}\" - "
                 "render the densest projection", toon=args.toon)
    else:
        emit.nxt(f"keel render {slice_str} - nothing to cross; declared views still render",
                 toon=args.toon)


def grid(m):
    """Aligned text grid: group separator lines, `.` for a derived-empty cell, multiple
    pivots in one cell separated by two spaces."""
    def chips(rt, ct):
        ps = m['cell'].get((rt, ct), [])
        return '  '.join(f"{MATRIX_GLYPH[m['state'][p]]} {p}" for p in ps) or '.'

    rw = max(len(m['row_kind']), *[len(r) for r in m['rows']],
             *[len(g) + 3 for g, _ in m['groups'] if g], 0) + 2
    cw = {c: max(len(c), *[len(chips(r, c)) for r in m['rows']]) + 2 for c in m['cols']}
    print(f"{m['row_kind']:<{rw}}" + ''.join(f"{c:<{cw[c]}}" for c in m['cols']))
    total = rw + sum(cw.values())
    for g, rids in m['groups']:
        if g:
            print(f"-- {g} " + '-' * max(0, total - len(g) - 4))
        for rt in rids:
            print((f"{rt:<{rw}}"
                   + ''.join(f"{chips(rt, c):<{cw[c]}}" for c in m['cols'])).rstrip())


def main():
    args = emit.parse(sys.argv[1:], cmd='matrix')
    words, slice_args = [], []
    for a in args.positional:
        (slice_args if Path(a).exists() else words).append(a)
    paths = resolve_paths(slice_args)
    slices, tables, _ = load_union(paths)
    names = ', '.join(n for n, _, _ in slices)
    # hints print the human-typeable form: a container path compresses back to its slug
    slice_str = ' '.join(containers.display_arg(a) for a in slice_args) or '.'

    if not words:
        return discover(tables, names, slice_str, args)
    if len(words) not in (2, 3):
        emit.die('USAGE', 'matrix takes <pivot> "<row-kind> x <col-kind>" [group-kind] - '
                 f"got {len(words)} non-path args ({', '.join(map(repr, words))})")
    pivot, axes = words[0], words[1]
    gk = words[2] if len(words) == 3 else ''
    if pivot not in tables or pivot in SYSTEM_TABLES:
        emit.die('TABLE_NOT_FOUND', f"'{pivot}' is not a node table in the loaded union "
                 f"(tables: {', '.join(n for n in tables if n not in SYSTEM_TABLES)})",
                 exit_code=3)
    pair = MATRIX_AXES.split(axes.strip(), maxsplit=1)
    if len(pair) != 2:
        emit.die('USAGE', f"axes {axes!r} must be '<row-kind> x <col-kind>'")
    kinds = {e['kind'] for e in tables.get('edges', [])}
    for k in (*pair, *([gk] if gk and gk != '@table' else [])):
        if k not in kinds:                 # a typo'd kind must not render an empty grid
            emit.die('KIND_NOT_FOUND', f"no '{k}' edges in the loaded union "
                     f"(kinds: {', '.join(sorted(kinds))})", exit_code=3)

    root = emit.default_root(args.root, paths)
    implemented, _, drifted, _, _ = classify(tables, root)
    m = build_matrix(tables, {'table': pivot, 'arg': axes, 'extra': gk},
                     real={'implemented': set(implemented),
                           'drifted': {n for n, _ in drifted}})
    gcands = [] if gk else group_candidates(tables, m['rows'])

    if args.toon:
        scalars = {'slices': names, 'root': root, 'pivot': pivot,
                   'axes': f"{m['row_kind']} x {m['col_kind']}"}
        if gk:
            scalars['group'] = gk
        scalars.update({'rows': len(m['rows']), 'cols': len(m['cols']),
                        'filled': m['filled'], 'uncovered_rows': len(m['uncovered']),
                        'unused_cols': len(m['unused'])})
        tbls = {'cells': matrix_toon_rows(m),
                'onesided': (['via', 'has'],
                             [{'via': p, 'has': k} for p, k in m['onesided']])}
        if gk:
            tbls['ungrouped'] = (['id'], [{'id': r} for r in m['ungrouped']])
            tbls['multigrouped'] = (['id', 'edges', 'took'],
                                    [{'id': r, 'edges': n, 'took': g}
                                     for r, n, g in m['multigrouped']])
        else:
            tbls['groupable'] = (['kind', 'covered', 'groups'], gcands)
        print(emit.toon(scalars, tbls))
    else:
        print(f"matrix [{names}]  {pivot}: {m['row_kind']} x {m['col_kind']}"
              + (f"  grouped by {gk}" if gk else '') + f"  root={root}")
        print(f"rows {len(m['rows'])} | cols {len(m['cols'])} | filled {m['filled']} | "
              f"uncovered rows {len(m['uncovered'])} | unused cols {len(m['unused'])}\n")
        if not m['rows'] or not m['cols']:
            print(f"(0 cells - no {m['row_kind']}/{m['col_kind']} edges leave "
                  f"{pivot} nodes)")
        else:
            grid(m)
        print(f"\nglyphs: {matrix_legend(verified=True)}")
        if m['uncovered']:
            print('uncovered rows: ' + ', '.join(m['uncovered']))
        if m['unused']:
            print('unused cols: ' + ', '.join(m['unused']))
        if m['onesided']:
            print('one-sided pivots: '
                  + '; '.join(f"{p} ({k} only)" for p, k in m['onesided']))
        for line in matrix_fit_lines(m):
            print(line)
        if gcands:
            print('groupable by: ' + '; '.join(
                f"{c['kind']} ({c['covered']}/{len(m['rows'])} rows -> {c['groups']} "
                f"groups)" for c in gcands))

    if gcands:                             # a flat grid with a partition in reach: regroup first
        emit.nxt(f"keel matrix {slice_str} {pivot} \"{m['row_kind']} x {m['col_kind']}\" "
                 f"{gcands[0]['kind']} - regroup the rows "
                 f"({gcands[0]['groups']} groups)", toon=args.toon)
    else:
        emit.nxt(f"lock it when it earns its keep - add a views row: matrix,<Title>,{pivot},"
                 f"\"{m['row_kind']} x {m['col_kind']}\"" + (f",{gk}" if gk else ',')
                 + " - render then regenerates it with the graph", toon=args.toon)


if __name__ == '__main__':
    main()
