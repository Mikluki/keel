#!/usr/bin/env python3
"""render: a domain-AGNOSTIC renderer for any spec-graph.

The engine knows only: nodes (rows with an `id`), `edges`, `views`, `rules`.
What node/edge KINDS exist and which VIEWS to draw are declared as data in the
.toon slices - this file contains no domain vocabulary. Four view primitives:

    table  - list a node table's columns
    join   - per node, edges of a kind touching it -> the other endpoint + a column
    entry  - per node, every row that `touches` it + its prose body + logic ref
    matrix - two edge kinds crossed through a pivot table -> coverage grid (gaps included)

Every node renders; the prose appendix is GROUPED by commitment state under `# Canon`,
`# Explore`, `# Dropped` (canon -> explore -> dropped), so nothing is hidden but the
rejected graveyard sits last where it is easy to skip. See render.state_of.

    python render.py                                      # all *.graph.toon in cwd
    python render.py a.graph.toon b.graph.toon a.views.toon   # union several slices
    python render.py toons/<slug>                        # a graph dir's slices
"""
import csv
import re
import sys
from pathlib import Path

import containers
import emit

HEADER = re.compile(r'^(\w+)\[(\d+)\]\{([^}]+)\}:\s*$')
SYSTEM_TABLES = {'edges', 'views', 'rules'}
RESERVED_COLS = {'id', 'state', 'touches'}   # structural columns; everything else is a prose cell
STATES = ('canon', 'explore', 'dropped')   # declared commitment axis; an unset state is canon
BODY_HEADING = re.compile(r'^(#{1,6})(?=\s|$)')   # an ATX heading line inside a prose body
FENCE = re.compile(r'^\s*(?:```+|~~~+)')          # a fenced-code delimiter (its `#`s are code)


def state_of(row):
    """A node's declared COMMITMENT state (canon/explore/dropped); an unset state is 'canon'.

    Orthogonal to the DERIVED realization axis (planned/implemented/drifted, computed from
    ref resolution): state says whether we have committed to the idea, not whether it is
    built. explore = provisional/under-evaluation; canon = accepted design; dropped =
    explored then rejected, kept as a record. Unknown values are treated as canon here;
    lint flags them.
    """
    st = row.get('state') or 'canon'
    return st if st in STATES else 'canon'


def parse_toon(text, src=''):
    """Minimal TOON reader: `key: value` scalars and `name[N]{cols}:` tables.

    Rows are read STRUCTURALLY - every non-blank line after the header until a blank
    line or the next header - and the declared [N] is validated as a checksum, never
    trusted. Trusting it corrupted silently both ways: an undercount leaked leftover
    rows into the scalars, an overcount ate the next table's header. A mismatch dies
    loud with both numbers, so a surgical row edit costs at most a one-line count fix.
    """
    scalars, tables, lines, i = {}, {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = HEADER.match(line)
        if m:
            name, n = m.group(1), int(m.group(2))
            cols = [c.strip() for c in m.group(3).split(',')]
            rows = []
            i += 1
            while i < len(lines) and lines[i].strip() and not HEADER.match(lines[i]):
                rows.append(dict(zip(cols, next(csv.reader([lines[i].strip()])))))
                i += 1
            if len(rows) != n:
                where = f" in {src}" if src else ''
                emit.die('BAD_COUNT', f"table '{name}'{where} declares {n} rows but has "
                         f"{len(rows)} - fix the count to [{len(rows)}] (a table's rows "
                         f"end at a blank line or the next header)")
            tables[name] = rows
        elif ':' in line:
            key, val = line.split(':', 1)
            scalars[key.strip()] = val.strip()
            i += 1
        else:
            i += 1
    return scalars, tables


def split(field):
    return [t.strip() for t in field.split(',') if t.strip()]


SLICE_GLOBS = ('*.graph.toon', '*.views.toon', '*.results.toon')


def dir_slices(d):
    """Every slice file in a directory: graph slices first, then views (a SYSTEM_TABLE,
    so lint/drift/status/context are unaffected; only render gains its views), then any OPT-IN
    `*.results.toon` measurement sidecar. Recognizing the results glob has no effect when the
    file is absent (the common case); when present it unions so its `touches`/`ref` back to
    graph nodes resolve, while its high-churn diffs stay isolated in their own file."""
    return [f for g in SLICE_GLOBS for f in sorted(Path(d).glob(g))]


def resolve_paths(args):
    if not args:
        return dir_slices('.')
    out = []
    for a in args:
        p = Path(a)
        out.extend(dir_slices(p) if p.is_dir() else [p])
    return out


def load_union(paths):
    """Union several slices: tables concatenate; track each node's home slice."""
    tables, prov, slices = {}, {}, []
    for p in paths:
        scalars, t = parse_toon(Path(p).read_text(), src=str(p))
        name = scalars.get('slice', Path(p).stem)
        slices.append((name, scalars, Path(p).parent))
        for tname, rows in t.items():
            tables.setdefault(tname, []).extend(rows)
            if tname not in SYSTEM_TABLES:
                for r in rows:
                    if 'id' in r:
                        prov[r['id']] = name
    return slices, tables, prov


CELL_MAX = 200   # a prose cell is a one-liner; past this it has grown into a paragraph
CELL_HARD_MAX = 3000   # ~500 words / half an editor screen; past this a cell is a body in a cell


def cell_warnings(tables, slices, prov, limit=CELL_MAX):
    """Prose cells that have outgrown a one-liner into a paragraph - a soft, NON-gating smell.

    A prose cell is every NON-reserved column on a node row: reserved (RESERVED_COLS =
    id/state/touches) is structure, everything else - card, why, chose, rejected, statement,
    ... - is a one-liner whose full form belongs in bodies/<id>.md, with MEASURED numbers in a
    results sidecar. Deriving the CLASS (non-reserved) rather than naming columns is the point:
    any new free-text column is covered the day it is added, and short columns (layer, tier,
    run) never reach the limit, so the same rule over every cell is free. `check` drift-checks
    code refs but never a cell, so a stale result pasted into one passes green forever. Returns
    one entry per offending CELL as {id, col, len, has_body}, longest first; has_body flags the
    split-brain case (a long cell that ALSO has a body - the same rationale in two places).
    Measurement rows (the results-sidecar shape, `finding` + `touches`) are exempt via the SAME
    predicate as measured_ids so the two never drift - the sidecar is the home for churny numbers.
    """
    root_of = {name: d for name, _, d in slices}
    out = []
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'finding' in r and 'touches' in r:   # a measurement row (see measured_ids) - exempt
                continue
            offenders = [(col, len(val)) for col, val in r.items()
                         if col not in RESERVED_COLS and len(val) > limit]
            if not offenders:
                continue
            nid = r.get('id', '?')
            body = root_of.get(prov.get(nid), Path('.')) / 'bodies' / f'{nid}.md'
            has_body = body.exists()
            out += [{'id': nid, 'col': col, 'len': n, 'has_body': has_body}
                    for col, n in offenders]
    return sorted(out, key=lambda w: -w['len'])


def cell_errors(tables, slices, prov, limit=CELL_HARD_MAX):
    """Prose cells so long they are a body pasted into a table cell - a HARD gate (exit 1).

    The hard companion to cell_warnings: SAME per-CELL, non-reserved, measurement-exempt
    derivation, but at L2 (CELL_HARD_MAX) a cell has no honest reading left - it is a body, not
    a one-liner, and its home is bodies/<id>.md. This tier gates CANON only (state_of == canon);
    explore and dropped still earn the soft warn, so nothing is invisible, and canon-only matches
    keel's other hard gates (needs-edge, canon-depends-on-explore) - a still-provisional idea is
    not held to the shipping bar. Returns one entry per offending CANON cell as {id, col, len},
    longest first; `check` appends each to its errors. slices/prov mirror cell_warnings' signature.
    """
    out = []
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'finding' in r and 'touches' in r:   # a measurement row (see measured_ids) - exempt
                continue
            if state_of(r) != 'canon':              # hard tier gates canon only (see docstring)
                continue
            out += [{'id': r.get('id', '?'), 'col': col, 'len': len(val)}
                    for col, val in r.items()
                    if col not in RESERVED_COLS and len(val) > limit]
    return sorted(out, key=lambda w: -w['len'])


_NUM_LEAK = re.compile(r'\d+\.\d+|\d+\s*/\s*\d+|\d+[eE][+-]?\d+|[~±]\s*\d')


def leaked_numbers(tables, slices, prov):
    """Measured/empirical numbers stranded in a prose cell that has no drift-checked home.

    The inverse of measured_ids: a CHOSEN number's home is a ref'd constant (file#CONST, which
    drift.py verifies) and a MEASURED one's is a results-sidecar `finding`; a number sitting in a
    prose cell on a node with NEITHER rots green - `check` drift-checks refs, never a cell, so a
    stale value there passes forever. Scans every NON-reserved cell (A's class) and flags a node
    with no `ref` edge that is also not measured (measured_ids). _NUM_LEAK matches only empirical
    SHAPES - decimals (4.75), ratios (13/20), sci-notation (8e4), a digit next to ~/± (~4160) -
    and deliberately SKIPS bare integers ('pinned at 25'), where false positives explode.

    Warn-only and heuristic, so known false positives are accepted: version strings ('Python
    3.14') and dates ('07/18') read as decimals/ratios, and exempt-if-ref means a ref'd node can
    still hide a pasted value - a deliberate trade so the warning stays credible (a leak on an
    unref'd, unmeasured node is the high-signal case). One entry per offending CELL as
    {id, col, hit} (hit = the matched token), most conspicuous first. slices/prov mirror the
    cell_warnings signature.
    """
    ref_ids = {e['from'] for e in tables.get('edges', []) if e['kind'] == 'ref'}
    measured = measured_ids(tables)
    out = []
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'finding' in r and 'touches' in r:   # a measurement row (see measured_ids) - exempt
                continue
            nid = r.get('id', '?')
            if nid in ref_ids or nid in measured:   # the number already has a drift-checked home
                continue
            for col, val in r.items():
                if col in RESERVED_COLS:
                    continue
                m = _NUM_LEAK.search(val)
                if m:
                    out.append({'id': nid, 'col': col, 'hit': m.group(0)})
    return sorted(out, key=lambda w: -len(w['hit']))


def weight_summary(tables, slices, prov):
    """The WEIGHT axis rolled up from the prose-cell detectors - one dict, single-sourced so
    status and index report the SAME numbers (mirrors classify's status<->index sharing).

    WIRING (drift/rules/orphans/seams) is structure; WEIGHT is prose rot, and a graph green on
    wiring can be obese on weight - reporting them apart is what stops green-on-wiring reading as
    green-overall. Five figures: prose_chars = total length of every NON-reserved cell on a
    non-SYSTEM, non-measurement row (the graph's prose-in-cells MASS, which check/drift never
    weigh); over_soft = cells past CELL_MAX (cell_warnings); over_hard = canon cells past
    CELL_HARD_MAX that gate check (cell_errors); leaked = empirical numbers with no drift-checked
    home (leaked_numbers); split_brain = long cells that ALSO have a body (has_body) - the same
    rationale committed in two places. Pure AGGREGATION: it adds no detector and moves no gate,
    and reuses each detector's measurement-row carve-out, so nothing here drifts from A/B/C.
    """
    prose_chars = 0
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'finding' in r and 'touches' in r:   # a measurement row (see measured_ids) - exempt
                continue
            prose_chars += sum(len(v) for c, v in r.items() if c not in RESERVED_COLS)
    warns = cell_warnings(tables, slices, prov)
    return {'prose_chars': prose_chars,
            'over_soft': len(warns),
            'over_hard': len(cell_errors(tables, slices, prov)),
            'leaked': len(leaked_numbers(tables, slices, prov)),
            'split_brain': sum(1 for w in warns if w['has_body'])}


def lookup(tables, node_id):
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if r.get('id') == node_id:
                return r
    return None


ENTRY_BODY_LINES = 8     # entry dumps many bodies; keep each compact (P3)


def slug(title):
    """A valid TOON table name (\\w+) derived from a human view title."""
    return re.sub(r'\W+', '_', title).strip('_') or 'view'


# ---- structured builders: each view -> (cols, rows) computed once, rendered either way ----

def build_table(tables, spec, ctx):
    cols = split(spec['arg'])
    return cols, [{c: r.get(c, '') for c in cols}
                  for r in tables.get(spec['table'], []) if ctx['keep'](r)]


def build_join(tables, spec, ctx):
    """Per node in spec.table: edges of kind spec.arg touching it -> other end + spec.extra col."""
    extra = spec.get('extra') or 'via'
    cols, rows = ['node', 'other', extra], []
    for r in tables.get(spec['table'], []):
        if not ctx['keep'](r):
            continue
        nid = r['id']
        for e in tables.get('edges', []):
            if e['kind'] != spec['arg']:
                continue
            other = e['to'] if e['from'] == nid else (e['from'] if e['to'] == nid else None)
            if other is None:
                continue
            tgt = lookup(tables, other)
            val = (tgt.get(spec['extra'], '') if spec['extra'] else '') if tgt \
                else '?? not in any loaded slice'
            rows.append({'node': nid, 'other': other, extra: val})
    return cols, rows


MATRIX_AXES = re.compile(r'\s+x\s+')   # "treats x measures-with" -> the two edge kinds
MATRIX_GLYPH = {'measured': '#', 'implemented': '=', 'refd': '=', 'drifted': '!',
                'planned': '~', 'dropped': 'x', 'explore': '?'}


def matrix_legend(verified):
    """One glyph vocabulary, two evidence strengths: render never resolves refs (graph-only),
    so its `=` means ref'd; the matrix command classifies against code and splits =/!."""
    impl = '= implemented  ! drifted' if verified else "= ref'd (drift-unchecked)"
    return f"# measured  {impl}  ~ planned  x dropped  ? explore"


def measured_ids(tables):
    """Nodes some finding row `touches`: a row carrying BOTH `touches` and `finding` columns
    is a measurement (the results-sidecar shape, detected structurally - never by table
    name), and everything it touches counts as measured."""
    out = set()
    for name, rows in tables.items():
        if name in SYSTEM_TABLES:
            continue
        for r in rows:
            if 'finding' in r and 'touches' in r:
                out.update(split(r['touches']))
    return out


def build_matrix(tables, spec, real=None):
    """The coverage pivot: rows = targets of spec.arg's first edge kind leaving spec.table
    nodes, cols = the second kind's, each cell the pivot node(s) joining the pair, carrying
    an EVIDENCE state: dropped > measured (see measured_ids) > explore > drifted/implemented
    (only when `real`, a caller's classify() split, is given) > refd (has a ref edge) >
    planned. spec.extra optionally groups rows: an edge kind (the row-node's FIRST such
    edge, spec order, wins; missing/extra edges are reported ungrouped/multigrouped) or
    the reserved '@table' (group by home table).

    Rows/cols are the kinds' TARGETS - a node no pivot points at is not a row; the
    uncovered/unused lists mark gaps WITHIN the projected set. All ordering is spec order
    (pivot-table row order), so the matrix is stable under re-render.
    """
    axes = MATRIX_AXES.split(spec['arg'].strip(), maxsplit=1)
    if len(axes) != 2:
        emit.die('BAD_VIEW', f"matrix arg {spec['arg']!r} must be '<row-kind> x <col-kind>'")
    row_kind, col_kind = axes
    edges = tables.get('edges', [])
    pivot_rows = tables.get(spec['table'], [])
    ordered = [r['id'] for r in pivot_rows if r.get('id')]
    pset = set(ordered)

    rows_of, cols_of = {}, {}
    for e in edges:
        if e['from'] in pset:
            if e['kind'] == row_kind:
                rows_of.setdefault(e['from'], []).append(e['to'])
            elif e['kind'] == col_kind:
                cols_of.setdefault(e['from'], []).append(e['to'])

    measured, refd = measured_ids(tables), {e['from'] for e in edges if e['kind'] == 'ref'}
    state = {}
    for r in pivot_rows:
        pid, st = r.get('id'), state_of(r)
        if st == 'dropped':
            state[pid] = 'dropped'
        elif pid in measured:
            state[pid] = 'measured'
        elif st == 'explore':
            state[pid] = 'explore'
        elif real is not None and pid in real['drifted']:
            state[pid] = 'drifted'
        elif real is not None and pid in real['implemented']:
            state[pid] = 'implemented'
        elif pid in refd:
            state[pid] = 'refd'
        else:
            state[pid] = 'planned'

    row_ids, col_ids, seen_r, seen_c = [], [], set(), set()
    cell = {}
    for p in ordered:
        for t in rows_of.get(p, ()):
            if t not in seen_r:
                seen_r.add(t)
                row_ids.append(t)
        for t in cols_of.get(p, ()):
            if t not in seen_c:
                seen_c.add(t)
                col_ids.append(t)
        for rt in rows_of.get(p, ()):
            for ct in cols_of.get(p, ()):
                ps = cell.setdefault((rt, ct), [])
                if p not in ps:
                    ps.append(p)

    gk = spec.get('extra') or ''
    group_of, ungrouped, multi = {}, [], []
    if gk == '@table':                     # reserved: group rows by their home table
        home = {r.get('id'): n for n, trs in tables.items()
                if n not in SYSTEM_TABLES for r in trs if 'id' in r}
        group_of = {rid: home.get(rid, '') for rid in row_ids}
    elif gk:
        rowset, fan = set(row_ids), {}
        for e in edges:
            if e['kind'] == gk and e['from'] in rowset:
                fan.setdefault(e['from'], []).append(e['to'])
        group_of = {r: ts[0] for r, ts in fan.items()}    # first edge (spec order) wins
        ungrouped = [r for r in row_ids if r not in group_of]
        multi = [(r, len(ts), group_of[r]) for r, ts in fan.items() if len(ts) > 1]
    groups, order = {}, []
    for rid in row_ids:
        g = group_of.get(rid, '')
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(rid)

    return {'row_kind': row_kind, 'col_kind': col_kind, 'group_kind': gk,
            'rows': row_ids, 'cols': col_ids, 'cell': cell, 'state': state,
            'ungrouped': ungrouped, 'multigrouped': multi,
            'groups': [(g, groups[g]) for g in order], 'filled': len(cell),
            'uncovered': [r for r in row_ids if not any((r, c) in cell for c in col_ids)],
            'unused': [c for c in col_ids if not any((r, c) in cell for r in row_ids)],
            'onesided': [(p, row_kind if p in rows_of else col_kind)
                         for p in ordered if (p in rows_of) != (p in cols_of)]}


def body_path(nid, ctx):
    """Where a node's prose body lives: <its slice's dir>/bodies/<id>.md."""
    home = ctx['prov'].get(nid)
    return ctx['root_of'].get(home, Path('.')) / 'bodies' / f"{nid}.md"


def build_bodies(tables, ctx):
    """Every kept node's FULL prose body, spec-ordered - the render's self-contained
    reference appendix. `entry` clips bodies (P3); this dumps the whole text so the
    live-preview file holds the complete spec without opening each bodies/<id>.md."""
    keep, items, seen = ctx['keep'], [], set()
    for tname, rows in tables.items():
        if tname in SYSTEM_TABLES:
            continue
        for r in rows:
            nid = r.get('id')
            if not nid or nid in seen or not keep(r):
                continue
            bpath = body_path(nid, ctx)
            if not bpath.exists():
                continue
            seen.add(nid)
            items.append({'id': nid, 'state': state_of(r), 'card': r.get('card', ''),
                          'body': bpath.read_text().strip()})
    return items


def build_entry(tables, spec, ctx):
    """Richer than a flat table: per node its constraints, logic ref, and prose body."""
    prov, logic, keep = ctx['prov'], ctx['logic'], ctx['keep']
    items = []
    for r in tables.get(spec['table'], []):
        if not keep(r):
            continue
        nid = r['id']
        constraints = []
        for tname, rows in tables.items():
            if tname in SYSTEM_TABLES:
                continue
            for rr in rows:
                if 'touches' in rr and nid in split(rr['touches']):
                    constraints.append((rr['id'], rr.get('statement') or rr.get('why')
                                        or rr.get('card') or ''))
        home = prov.get(nid)
        bpath = body_path(nid, ctx)
        items.append({'id': nid, 'state': state_of(r), 'card': r.get('card', ''),
                      'constraints': constraints, 'logic': logic.get(home) or '',
                      'body': bpath.read_text().strip() if bpath.exists() else ''})
    return items


# ---- human renderers ----

def demote_body_headings(body, under):
    """Push a body's own markdown headings down so its shallowest sits one level below
    `under` (the `### <id>` heading it renders beneath) - otherwise a body's `#`/`##`
    escapes its section and flattens the outline. Relative depth within the body is
    preserved (all headings shift by the same amount); `#`s inside fenced code are left
    alone; nothing goes past h6."""
    lines = body.splitlines()
    fenced, levels = False, []
    for ln in lines:
        if FENCE.match(ln):
            fenced = not fenced
        elif not fenced:
            m = BODY_HEADING.match(ln)
            if m:
                levels.append(len(m.group(1)))
    shift = max(0, under + 1 - min(levels)) if levels else 0
    if not shift:
        return body
    out, fenced = [], False
    for ln in lines:
        if FENCE.match(ln):
            fenced = not fenced
            out.append(ln)
            continue
        m = BODY_HEADING.match(ln)
        if m and not fenced:
            h = m.group(1)
            out.append('#' * min(6, len(h) + shift) + ln[len(h):])
        else:
            out.append(ln)
    return '\n'.join(out)


def human_table(cols, rows):
    out = ['| ' + ' | '.join(cols) + ' |', '| ' + ' | '.join('---' for _ in cols) + ' |']
    return out + ['| ' + ' | '.join(r.get(c, '') for c in cols) + ' |' for r in rows]


def human_join(spec, cols, rows):
    """One markdown bullet per edge, split so it aligns AND wraps. Only the short
    `node -[kind]- other` spine sits in a code span: inside code markdown preserves the node
    padding, so the -[kind]- arrows stay column-aligned (plain padding gets collapsed) - and it
    is short enough to never trigger a horizontal scrollbar. The extra column (often long prose)
    follows as normal text, so it WRAPS instead of overflowing the code box into a scroll slider."""
    if not rows:
        return list(rows)
    nw = max(len(r['node']) for r in rows)
    lines = []
    for r in rows:
        val = r.get(cols[2], '')
        line = f"- `{r['node']:<{nw}} -[{spec['arg']}]- {r['other']}`"
        lines.append(f"{line}: {val}" if val else line)
    return lines


def human_matrix(spec, m):
    """A markdown coverage grid: group rows bolded, `.` for a derived-empty cell, then a
    glyph legend and the gap lines - the empty cells are the payload, so uncovered rows /
    unused cols are named explicitly (P5), never left to be inferred from the dots."""
    if not m['rows'] or not m['cols']:
        return [f"(0 cells - no {m['row_kind']}/{m['col_kind']} edges leave "
                f"{spec['table']} nodes)"]

    def chips(rt, ct):
        ps = m['cell'].get((rt, ct), [])
        return ', '.join(f"{MATRIX_GLYPH[m['state'][p]]} {p}" for p in ps) or '.'

    head = [f"{m['row_kind']} x {m['col_kind']}"] + m['cols']
    out = ['| ' + ' | '.join(head) + ' |',
           '| ' + ' | '.join('---' for _ in head) + ' |']
    for g, rids in m['groups']:
        if g:
            out.append('| ' + ' | '.join([f"**{g}**"] + ['' for _ in m['cols']]) + ' |')
        out += ['| ' + ' | '.join([rt] + [chips(rt, c) for c in m['cols']]) + ' |'
                for rt in rids]
    out += ['', f"glyphs: {matrix_legend(verified=False)}"]
    if m['uncovered']:
        out.append(f"uncovered rows ({len(m['uncovered'])}): " + ', '.join(m['uncovered']))
    if m['unused']:
        out.append(f"unused cols ({len(m['unused'])}): " + ', '.join(m['unused']))
    if m['onesided']:
        out.append('one-sided pivots: '
                   + '; '.join(f"{p} ({k} only)" for p, k in m['onesided']))
    out += matrix_fit_lines(m)
    return out


def matrix_fit_lines(m):
    """How well the declared group kind fits the rows - a bad fit must not stay silent:
    a row without the edge lands in an unlabeled bucket, a row with several takes the
    first, and both get named here (probe and locked view alike)."""
    out = []
    if m['ungrouped']:
        out.append(f"ungrouped rows ({len(m['ungrouped'])}): " + ', '.join(m['ungrouped']))
    if m['multigrouped']:
        out.append('multi-grouped: ' + '; '.join(
            f"{r} ({n} {m['group_kind']} edges, took {g})"
            for r, n, g in m['multigrouped']))
    return out


def matrix_toon_rows(m):
    """One row per (pair, pivot) cell; gaps stay first-class rows an agent can branch on:
    an uncovered row / unused col appears with the other coordinate empty (P5)."""
    rows = [{'row': rt, 'col': ct, 'via': p, 'state': m['state'][p]}
            for (rt, ct), ps in m['cell'].items() for p in ps]
    rows += [{'row': r, 'col': '', 'via': '', 'state': 'uncovered'} for r in m['uncovered']]
    rows += [{'row': '', 'col': c, 'via': '', 'state': 'unused'} for c in m['unused']]
    return ['row', 'col', 'via', 'state'], rows


def human_entry(items, full):
    out = []
    for it in items:
        tag = '' if it['state'] == 'canon' else f"  [{it['state']}]"
        out.append(f"### {it['id']}" + (f" - {it['card']}" if it['card'] else '') + tag)
        out.append('')
        out += [f"> {cid}: {msg}" for cid, msg in it['constraints']]
        if it['logic']:
            out.append(f"Logic -> {it['logic']}")
        if it['body']:
            n = len(it['body'].splitlines()) if full else ENTRY_BODY_LINES
            demoted = demote_body_headings(it['body'], under=3)
            out.append('')
            out.append(emit.clip(demoted, n, f"full: read bodies/{it['id']}.md or pass --full"))
        out.append('')
    return out


def human_bodies(items):
    """One commitment group's full-prose bodies: `## <id> - <card>` then the whole body,
    its own headings demoted to nest below that `##`. The caller's `# <State>` heading
    already carries the state, so there is no per-item tag."""
    out = []
    for it in items:
        out.append(f"## {it['id']}" + (f" - {it['card']}" if it['card'] else ''))
        out.append('')
        out.append(demote_body_headings(it['body'], under=2))
        out.append('')
    return out


def entry_toon_rows(items):
    return ['id', 'state', 'card', 'constraints', 'logic', 'body'], [
        {'id': it['id'], 'state': it['state'], 'card': it['card'], 'logic': it['logic'],
         'constraints': ' | '.join(f"{c}: {m}" for c, m in it['constraints']),
         'body': f"bodies/{it['id']}.md ({len(it['body'].splitlines())} lines)"
                 if it['body'] else ''}
        for it in items]


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='render')
    slices, tables, prov = load_union(resolve_paths(args.positional))
    logic, root_of = {}, {}
    for name, scalars, parent in slices:
        m = re.search(r'logic:\s*([^,}]+)', scalars.get('refs', ''))
        logic[name] = m.group(1).strip() if m else None
        root_of[name] = parent
    # nothing is hidden: every node renders and the bodies appendix groups by commitment state.
    ctx = {'prov': prov, 'logic': logic, 'root_of': root_of, 'keep': lambda _: True}
    views = tables.get('views', [])
    names = ', '.join(n for n, _, _ in slices)
    slice_args = ' '.join(containers.display_arg(a) for a in args.positional) or '.'

    if args.toon:
        toon_tables = {}
        for v in views:
            name = slug(v['title'])
            if v['kind'] == 'table':
                toon_tables[name] = build_table(tables, v, ctx)
            elif v['kind'] == 'join':
                toon_tables[name] = build_join(tables, v, ctx)
            elif v['kind'] == 'entry':
                toon_tables[name] = entry_toon_rows(build_entry(tables, v, ctx))
            elif v['kind'] == 'matrix':
                toon_tables[name] = matrix_toon_rows(build_matrix(tables, v))
            else:
                toon_tables[name] = (['note'], [{'note': f"unknown view kind: {v['kind']}"}])
        print(emit.toon({'slices': names, 'views': len(views)}, toon_tables))
        emit.nxt(f"edit the graph then keel check {slice_args} --code-root <code>",
                 toon=True, guide=True)
        return

    print(f"# Render - slices: {names}\n")
    print("(build output from views[]; do not hand-edit)\n")
    if not views:
        print("(0 views declared - nothing to render)")
    for v in views:
        print(f"## {v['title']}\n")
        if v['kind'] == 'table':
            cols, rows = build_table(tables, v, ctx)
            body = human_table(cols, rows) if rows else ["(0 rows)"]
        elif v['kind'] == 'join':
            cols, rows = build_join(tables, v, ctx)
            body = human_join(v, cols, rows) if rows else [f"(0 {v['arg']} edges)"]
        elif v['kind'] == 'entry':
            items = build_entry(tables, v, ctx)
            body = human_entry(items, args.full) if items else ["(0 nodes)"]
        elif v['kind'] == 'matrix':
            body = human_matrix(v, build_matrix(tables, v))
        else:
            body = [f"(unknown view: {v['kind']})"]
        print('\n'.join(body), '\n')
    # bodies appendix: the FULL prose of every node with a bodies/<id>.md, GROUPED by
    # commitment state (# Canon/# Explore/# Dropped) so the render is self-contained yet
    # the rejected nodes sit last where they are easy to skip.
    bodies = build_bodies(tables, ctx)
    for st in STATES:                       # canon -> explore -> dropped
        group = [it for it in bodies if it['state'] == st]
        if group:
            print(f"# {st.capitalize()}\n")
            print('\n'.join(human_bodies(group)), '\n')
    emit.nxt(f"edit the graph then keel check {slice_args} --code-root <code> - never hand-edit this output",
             guide=True)


if __name__ == '__main__':
    main()
