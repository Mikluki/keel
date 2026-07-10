# ABOUTME: guards the engine behaviors that are easy to break by accident: parse_toon's
# structural row reading + [N]-count checksum (a stale count must die loud, never corrupt
# silently), the emit.toon round-trip, and lint's rule kinds (undirected exemption from the
# canon-dependency gate, unknown-kind fail-loud). Lint runs end-to-end through cli.py on
# tmp_path fixtures; parse_toon is unit-tested directly (pythonpath=engine, see pyproject).
import subprocess
import sys
from pathlib import Path

import pytest

import emit
from drift import jump_of, resolve
from render import parse_toon

ENGINE = Path(__file__).resolve().parent.parent / 'engine'


# ============================================================================
# FUNCTIONS
# ============================================================================

def run_cli(cmd, *args):
    """Run `cli.py <cmd> <args...>` exactly as an agent would; return the result."""
    return subprocess.run([sys.executable, str(ENGINE / 'cli.py'), cmd, *map(str, args)],
                          capture_output=True, text=True)


def write_slice(tmp_path, text):
    f = tmp_path / 'fix.graph.toon'
    f.write_text(text)
    return f


# ============================================================================
# parse_toon: count checksum + structural rows
# ============================================================================

def test_correct_count_parses():
    scalars, tables = parse_toon('slice: t\n\nnodes[2]{id,card}:\n  a,"x"\n  b,"y"\n')
    assert scalars['slice'] == 't'
    assert [r['id'] for r in tables['nodes']] == ['a', 'b']
    assert tables['nodes'][0]['card'] == 'x'


def test_undercount_dies_loud(capsys):
    # the old parser leaked leftover rows into the scalars (a cell colon made a garbage key)
    with pytest.raises(SystemExit) as e:
        parse_toon('nodes[1]{id,card}:\n  a,"has: a colon"\n  b,"y"\n', src='fix.toon')
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert 'BAD_COUNT' in err
    assert "'nodes'" in err and 'fix.toon' in err
    assert 'declares 1' in err and 'has 2' in err


def test_overcount_dies_loud(capsys):
    # the old parser ate the next table's header (or a blank line) as a row
    with pytest.raises(SystemExit) as e:
        parse_toon('nodes[3]{id,card}:\n  a,"x"\n  b,"y"\n\nedges[1]{kind,from,to}:\n  r,a,b\n')
    assert e.value.code == 2
    assert 'declares 3' in capsys.readouterr().err


def test_blank_line_ends_table():
    _, tables = parse_toon('a[1]{id}:\n  x\n\nb[1]{id}:\n  y\n')
    assert len(tables['a']) == 1 and len(tables['b']) == 1


def test_next_header_ends_table():
    # emit.toon writes tables back-to-back with no blank separator
    _, tables = parse_toon('a[1]{id}:\n  x\nb[1]{id}:\n  y\n')
    assert len(tables['a']) == 1 and len(tables['b']) == 1


def test_zero_row_table():
    # explicit-empty tables (emit.toon P5) at EOF and mid-file
    _, tables = parse_toon('a[0]{id}:\nb[1]{id}:\n  y\nc[0]{id}:\n')
    assert tables['a'] == [] and len(tables['b']) == 1 and tables['c'] == []


def test_rows_flush_left_or_indented():
    # hand-authored files are flush-left; emit.toon indents 2 spaces - both are rows
    _, tables = parse_toon('a[2]{id}:\nx\n  y\n')
    assert [r['id'] for r in tables['a']] == ['x', 'y']


def test_quoted_comma_and_colon_stay_in_cell():
    scalars, tables = parse_toon('k: v\n\na[1]{id,card}:\n  x,"fleet: median, IQR"\n')
    assert tables['a'][0]['card'] == 'fleet: median, IQR'
    assert scalars == {'k': 'v'}          # the cell colon must not mint a scalar


def test_emit_toon_round_trips():
    text = emit.toon({'slices': 't', 'n': 2},
                     {'rows': (['id', 'card'], [{'id': 'a', 'card': 'x, y: z'},
                                                {'id': 'b', 'card': 'plain'}]),
                      'empty': (['ref'], [])})
    scalars, tables = parse_toon(text)
    assert scalars == {'slices': 't', 'n': '2'}
    assert tables['rows'][0]['card'] == 'x, y: z'
    assert len(tables['rows']) == 2 and tables['empty'] == []


# ============================================================================
# lint through cli.py: state gate + rule kinds
# ============================================================================

GATE_SLICE = '''slice: t
n[2]{id,state,card}:
  a,canon,"kept"
  b,dropped,"rejected"

edges[1]{kind,from,to}:
  overlaps,a,b
'''


def test_canon_depending_on_dropped_fails(tmp_path):
    r = run_cli('lint', write_slice(tmp_path, GATE_SLICE))
    assert r.returncode == 1
    assert "canon 'a' depends on dropped 'b'" in r.stdout


def test_undirected_kind_exempt_from_gate(tmp_path):
    r = run_cli('lint', write_slice(
        tmp_path, GATE_SLICE + '\nrules[1]{kind,a,b}:\n  undirected,overlaps,\n'))
    assert r.returncode == 0, r.stdout + r.stderr


def test_unknown_rule_kind_fails(tmp_path):
    r = run_cli('lint', write_slice(
        tmp_path, GATE_SLICE + '\nrules[2]{kind,a,b}:\n  undriected,overlaps,\n  needs-edge,n,ref\n'))
    assert r.returncode == 1
    assert "unknown rule kind 'undriected'" in r.stdout


def test_bad_count_reaches_cli_user(tmp_path):
    # end-to-end: the checksum error must surface through cli.py with exit 2, not a traceback
    r = run_cli('lint', write_slice(tmp_path, 'n[2]{id}:\n  a\n'))
    assert r.returncode == 2
    assert 'BAD_COUNT' in r.stderr and 'Traceback' not in r.stderr


# ============================================================================
# card-length warning: soft, non-gating, scoped to `card`
# ============================================================================

def test_long_card_warns_but_does_not_gate(tmp_path):
    long = 'x' * 250
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{long}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr        # a prose card is a smell, not an error
    assert '1 warnings' in r.stdout                        # counted on the summary line (watch reads it)
    assert 'a' in r.stdout and 'chars' in r.stdout


def test_short_card_no_warning(tmp_path):
    r = run_cli('lint', write_slice(tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"short"\n'))
    assert r.returncode == 0
    assert '0 warnings' in r.stdout


def test_long_card_with_body_flags_split(tmp_path):
    # a long card that ALSO has a body = the same rationale in two places
    (tmp_path / 'bodies').mkdir()
    (tmp_path / 'bodies' / 'a.md').write_text('# a\nprose')
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{"y" * 250}"\n'))
    assert r.returncode == 0
    assert 'also has a body' in r.stdout


def test_long_finding_in_results_not_a_card_warning(tmp_path):
    # a result's `finding` is the earned home for a measured number - it must NOT trip the
    # card check (which is scoped to `card`), even at full length
    (tmp_path / 'g.graph.toon').write_text('slice: t\nn[1]{id,card}:\n  exp,"an experiment"\n')
    (tmp_path / 'g.results.toon').write_text(
        f'slice: t-res\nresult[1]{{id,touches,finding}}:\n  r-exp,exp,"{"z" * 300}"\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '0 warnings' in r.stdout


def test_results_sidecar_unions_from_dir(tmp_path):
    # the *.results.toon sibling auto-unions, so its `touches` back to a graph node resolves
    (tmp_path / 'g.graph.toon').write_text('slice: t\nn[1]{id,card}:\n  exp,"an experiment"\n')
    (tmp_path / 'g.results.toon').write_text(
        'slice: t-res\nresult[1]{id,touches,finding}:\n  r-exp,exp,"ran; ok"\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'unresolved cross-slice refs: 0' in r.stdout       # touches:exp resolved across files


# ============================================================================
# output is FULL by default; --brief opts into truncation
# ============================================================================

def _many_long_cards(k):
    rows = '\n'.join(f'  n{i},"{"x" * 250}"' for i in range(k))
    return f'slice: t\nn[{k}]{{id,card}}:\n{rows}\n'


def test_full_is_default_no_truncation(tmp_path):
    r = run_cli('lint', write_slice(tmp_path, _many_long_cards(15)))
    assert r.returncode == 0
    assert '15 warnings' in r.stdout
    assert 'more; --full' not in r.stdout            # nothing is clipped by default

def test_brief_opts_into_truncation(tmp_path):
    r = run_cli('lint', '--brief', write_slice(tmp_path, _many_long_cards(15)))
    assert r.returncode == 0
    assert '15 warnings' in r.stdout                  # the count is always full
    assert 'more; --full' in r.stdout                 # but the list clips under --brief


# ============================================================================
# todo: the derived worklist (ready/blocked/frees, lanes, goal cone)
# ============================================================================

TODO_SLICE = '''slice: t
n[4]{id,state,card}:
  base,canon,"built foundation"
  mid,canon,"buildable now"
  top,canon,"waits on mid"
  spike,explore,"an idea"

edges[3]{kind,from,to}:
  needs,mid,base
  needs,top,mid
  ref,base,lib.py
'''


def _todo_dir(tmp_path, slice_text=TODO_SLICE):
    (tmp_path / 'lib.py').write_text('def built(): pass\n')   # makes `base` implemented
    write_slice(tmp_path, slice_text)
    return tmp_path


def test_todo_ready_blocked_and_top_pick(tmp_path):
    d = _todo_dir(tmp_path)
    r = run_cli('todo', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'READY 1' in r.stdout and 'BLOCKED 1' in r.stdout
    assert '<- mid' in r.stdout                       # blocked `top`, with the why
    assert 'frees 1' in r.stdout                      # mid is top's last obstacle
    assert 'next: keel context mid' in r.stdout               # the ranked pick, not `base` (built)


def test_todo_fix_ranks_before_ready(tmp_path):
    # a drifted ref outranks buildable work: the graph is lying, reconcile first
    d = _todo_dir(tmp_path, TODO_SLICE
                     .replace('edges[3]', 'edges[4]')
                     .replace('  ref,base,lib.py\n', '  ref,base,lib.py\n  ref,top,gone.py\n'))
    r = run_cli('todo', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'FIX 1' in r.stdout
    assert 'next: keel context top' in r.stdout and 'reconcile' in r.stdout


def test_todo_goal_scopes_to_cone(tmp_path):
    d = _todo_dir(tmp_path)
    r = run_cli('todo', 'top', d, '--code-root', d, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['goal'] == 'top'
    assert [x['id'] for x in tables['ready']] == ['mid']
    assert tables['decide'] == []                     # spike is outside top's cone
    assert [x['id'] for x in tables['blocked']] == ['top']


def test_todo_goal_not_found(tmp_path):
    r = run_cli('todo', 'nosuch', _todo_dir(tmp_path))
    assert r.returncode == 3
    assert 'NODE_NOT_FOUND' in r.stderr


LANES_SLICE = '''slice: t
n[4]{id,card}:
  a1,"independent one"
  a2,"independent two"
  b1,"coupled pair - one"
  b2,"coupled pair - two"

edges[1]{kind,from,to}:
  overlaps,b1,b2

rules[1]{kind,a,b}:
  undirected,overlaps,
'''


def test_todo_lanes_from_coupling(tmp_path):
    # undirected `overlaps` is no prerequisite (all 4 stay ready) but it DOES couple
    # b1/b2 into one lane; the untouched a1/a2 each get their own parallel-safe lane
    write_slice(tmp_path, LANES_SLICE)
    r = run_cli('todo', tmp_path, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['ready'] == '4' and scalars['lanes'] == '3'
    lane = {x['id']: x['lane'] for x in tables['ready']}
    assert lane['b1'] == lane['b2']
    assert len({lane['a1'], lane['a2'], lane['b1']}) == 3


def test_todo_brief_clips_ready(tmp_path):
    rows = '\n'.join(f'  n{i},"card"' for i in range(6))
    write_slice(tmp_path, f'slice: t\nn[6]{{id,card}}:\n{rows}\n')
    full = run_cli('todo', tmp_path)
    brief = run_cli('todo', tmp_path, '--brief')
    assert 'n5' in full.stdout and 'drop --brief' not in full.stdout
    assert 'n5' not in brief.stdout and 'drop --brief' in brief.stdout


def test_todo_cycle_fails_loud(tmp_path):
    write_slice(tmp_path, 'slice: t\nn[2]{id,card}:\n  a,"x"\n  b,"y"\n\n'
                          'edges[2]{kind,from,to}:\n  needs,a,b\n  needs,b,a\n')
    r = run_cli('todo', tmp_path)
    assert r.returncode == 0
    assert 'READY 0' in r.stdout and 'cycle' in r.stdout


# ============================================================================
# matrix: the derived coverage pivot (command + render view kind)
# ============================================================================

MATRIX_SLICE = '''slice: t
exp[5]{id,state,card}:
  e-run,canon,"ran and measured"
  e-wired,canon,"built"
  e-plan,canon,"not started"
  e-drop,dropped,"rejected"
  e-agg,canon,"aggregator - treats only"

axis[3]{id,state,card}:
  d1,canon,"covered"
  d2,canon,"treated but never measured"
  d3,canon,"other arm"

lens[2]{id,state,card}:
  m1,canon,"metric one"
  m2,canon,"metric two"

home[2]{id,state,card}:
  h-synth,canon,"synthetic side"
  h-phys,canon,"physical side"

edges[15]{kind,from,to}:
  treats,e-run,d1
  treats,e-wired,d3
  treats,e-plan,d3
  treats,e-drop,d3
  treats,e-agg,d1
  treats,e-agg,d2
  measures-with,e-run,m1
  measures-with,e-wired,m1
  measures-with,e-plan,m2
  measures-with,e-drop,m2
  ref,e-run,lib.py
  ref,e-wired,lib.py
  lives-in,d1,h-synth
  lives-in,d2,h-synth
  lives-in,d3,h-phys

result[1]{id,touches,run,finding,data}:
  r-1,e-run,"a run","departs the band","res/x.csv"
'''


def _matrix_dir(tmp_path, slice_text=MATRIX_SLICE):
    (tmp_path / 'lib.py').write_text('def built(): pass\n')
    write_slice(tmp_path, slice_text)
    return tmp_path


def test_matrix_evidence_glyphs_and_gaps(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', 'exp', 'treats x measures-with', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '# e-run' in r.stdout            # a finding row touches it -> measured
    assert '= e-wired' in r.stdout          # ref resolves -> implemented
    assert '~ e-plan' in r.stdout           # no ref -> planned
    assert 'x e-drop' in r.stdout           # declared dropped
    assert 'uncovered rows: d2' in r.stdout             # treated, zero cells
    assert 'e-agg (treats only)' in r.stdout            # pivot with one axis only


def test_matrix_groups_rows_by_kind(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', 'exp', 'treats x measures-with', 'lives-in', d,
                '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '-- h-synth' in r.stdout and '-- h-phys' in r.stdout
    # group order follows row rank: d1 appears first, so its group leads
    assert r.stdout.index('-- h-synth') < r.stdout.index('-- h-phys')


def test_matrix_discovery_ranks_candidates(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'treats x measures-with' in r.stdout
    assert '3 x 2' in r.stdout
    # the nxt hint hands over the exact render command for the top candidate
    assert f'keel matrix {d} exp "treats x measures-with"' in r.stdout


def test_matrix_toon_keeps_gaps_first_class(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', 'exp', 'treats x measures-with', d, '--code-root', d, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['filled'] == '3' and scalars['uncovered_rows'] == '1'
    cells = tables['cells']
    assert {'row': 'd1', 'col': 'm1', 'via': 'e-run', 'state': 'measured'} in cells
    assert {'row': 'd2', 'col': '', 'via': '', 'state': 'uncovered'} in cells
    assert tables['onesided'] == [{'via': 'e-agg', 'has': 'treats'}]


def test_matrix_unknown_pivot_and_kind_fail_loud(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', 'nope', 'treats x measures-with', d, '--code-root', d)
    assert r.returncode == 3 and 'TABLE_NOT_FOUND' in r.stderr
    r = run_cli('matrix', 'exp', 'bogus x measures-with', d, '--code-root', d)
    assert r.returncode == 3 and 'KIND_NOT_FOUND' in r.stderr


def test_matrix_view_kind_renders_markdown(tmp_path):
    # the locked form: a views row regenerates the grid on every render (graph-only,
    # so a resolving-or-not ref both show as `=` ref'd there)
    view_slice = MATRIX_SLICE + ('\nviews[1]{kind,title,table,arg,extra}:\n'
                                 '  matrix,Coverage,exp,"treats x measures-with",lives-in\n')
    d = _matrix_dir(tmp_path, view_slice)
    r = run_cli('render', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '## Coverage' in r.stdout
    assert '# e-run' in r.stdout and '= e-wired' in r.stdout
    assert '**h-synth**' in r.stdout
    assert 'uncovered rows (1): d2' in r.stdout


def test_matrix_flat_render_suggests_grouping(tmp_path):
    # rendered flat, the output names the partition and the nxt hint hands over the call
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', 'exp', 'treats x measures-with', d, '--code-root', d)
    assert 'groupable by: lives-in (3/3 rows -> 2 groups)' in r.stdout
    assert f'keel matrix {d} exp "treats x measures-with" lives-in' in r.stdout  # nxt: regroup
    # grouped, the suggestion disappears and the lock hint returns
    r = run_cli('matrix', 'exp', 'treats x measures-with', 'lives-in', d,
                '--code-root', d)
    assert 'groupable by' not in r.stdout and 'lock it' in r.stdout


def test_matrix_discovery_suggests_group(tmp_path):
    d = _matrix_dir(tmp_path)
    r = run_cli('matrix', d, '--code-root', d)
    assert 'group: lives-in (2)' in r.stdout


def test_matrix_group_fit_diagnostics(tmp_path):
    # d2 loses its lives-in edge (-> ungrouped) and d1 gains a second (first edge wins)
    twisted = MATRIX_SLICE.replace('lives-in,d2,h-synth', 'lives-in,d1,h-phys')
    d = _matrix_dir(tmp_path, twisted)
    r = run_cli('matrix', 'exp', 'treats x measures-with', 'lives-in', d,
                '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'ungrouped rows (1): d2' in r.stdout
    assert 'multi-grouped: d1 (2 lives-in edges, took h-synth)' in r.stdout


FALLBACK_SLICE = '''slice: t
p[2]{id,card}:
  p1,"x"
  p2,"y"

a[2]{id,card}:
  a1,"row"
  a2,"row"

b[1]{id,card}:
  b1,"row"

m[2]{id,card}:
  m1,"col"
  m2,"col"

edges[6]{kind,from,to}:
  r,p1,a1
  r,p1,b1
  r,p2,a2
  c,p1,m1
  c,p2,m2
  c,p2,m1
'''


def test_matrix_table_fallback_grouping(tmp_path):
    # no edge kind partitions the rows, but they span two tables -> @table suggested,
    # and passing it groups by home table
    write_slice(tmp_path, FALLBACK_SLICE)
    r = run_cli('matrix', 'p', 'r x c', tmp_path, '--code-root', tmp_path)
    assert 'groupable by: @table (3/3 rows -> 2 groups)' in r.stdout
    r = run_cli('matrix', 'p', 'r x c', '@table', tmp_path, '--code-root', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '-- a' in r.stdout and '-- b' in r.stdout


def test_matrix_hint_compresses_container_to_slug(tmp_path):
    # hints print the human-typeable form: a .toons/<slug>/ path arg compresses back to
    # the bare slug, slices-first - exactly what the shorthand re-expands on the next call
    cont = tmp_path / '.toons' / 'demo'
    cont.mkdir(parents=True)
    (tmp_path / 'lib.py').write_text('def built(): pass\n')
    (cont / 'demo.graph.toon').write_text(MATRIX_SLICE)
    r = run_cli('matrix', cont, 'exp', 'treats x measures-with', '--code-root', tmp_path)
    assert 'keel matrix demo exp "treats x measures-with" lives-in' in r.stdout


# ============================================================================
# refs.resolve: constants are symbols (the chosen-number discipline)
# ============================================================================

def test_resolve_python_constant(tmp_path):
    # a chosen number is ref'd by symbol, never copied into the graph - the resolver
    # must treat module-level assignments (bare and annotated) as definitions
    (tmp_path / 'consts.py').write_text('BOOT_REPS = 1000\nBAND_Q: float = 0.95\n')
    assert resolve('consts.py#BOOT_REPS', tmp_path)[0] == 'OK'
    assert resolve('consts.py#BAND_Q', tmp_path)[0] == 'OK'
    assert resolve('consts.py#GONE', tmp_path)[0] == 'MISSING-SYM'   # a rename fails the gate


def test_resolve_rust_constant(tmp_path):
    (tmp_path / 'consts.rs').write_text(
        'pub const BOOT_REPS: usize = 1000;\npub static BAND_Q: f64 = 0.95;\n')
    assert resolve('consts.rs#BOOT_REPS', tmp_path)[0] == 'OK'
    assert resolve('consts.rs#BAND_Q', tmp_path)[0] == 'OK'


# ============================================================================
# context: inline ref resolution (--code-root) + code->graph reverse lookup
# ============================================================================

CTX_SLICE = '''slice: t
n[2]{id,state,card}:
  boot,canon,"pre-registered bootstrap reps - deliberately not a CLI knob"
  other,canon,"unrelated"

edges[2]{kind,from,to}:
  ref,boot,lib.py#BOOT_REPS
  treats,other,boot
'''


def _ctx_dir(tmp_path):
    (tmp_path / 'lib.py').write_text('BOOT_REPS = 1000  # replicates\n')
    write_slice(tmp_path, CTX_SLICE)
    return tmp_path


def test_context_resolves_refs_inline_only_with_root(tmp_path):
    d = _ctx_dir(tmp_path)
    r = run_cli('context', 'boot', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'BOOT_REPS = 1000' not in r.stdout          # graph-only without the flag
    r = run_cli('context', 'boot', d, '--code-root', d)
    assert 'OK' in r.stdout and 'BOOT_REPS = 1000' in r.stdout
    assert 'lib.py:1' in r.stdout                      # the assembled file:line jump handle


def test_context_code_coordinate_reverse_lookup(tmp_path):
    # exact target, /-suffix, and bare symbol all name the same coordinate
    d = _ctx_dir(tmp_path)
    for q in ('lib.py#BOOT_REPS', 'BOOT_REPS'):
        r = run_cli('context', q, d)
        assert r.returncode == 0, r.stdout + r.stderr
        assert 'boot' in r.stdout and 'not a CLI knob' in r.stdout
    r = run_cli('context', 'BOOT_REPS', d, '--code-root', d)
    assert 'BOOT_REPS = 1000' in r.stdout              # rooted: the coordinate resolves too
    assert 'lib.py:1' in r.stdout
    r = run_cli('context', 'lib.py#GONE', d)           # neither node nor ref target
    assert r.returncode == 3
    assert 'neither a node id nor a ref target' in r.stderr


def test_context_toon_gains_code_table(tmp_path):
    d = _ctx_dir(tmp_path)
    r = run_cli('context', 'boot', d, '--code-root', d, '--toon')
    assert 'code[1]{status,target,location,evidence}' in r.stdout
    assert 'lib.py:1' in r.stdout
    r = run_cli('context', 'boot', d, '--toon')
    assert 'code[' not in r.stdout                     # no root, no code table


def test_hint_split_guide_human_only_remediation_both(tmp_path):
    # tour-guide hint (lint green -> "now check drift"): human sees it, agent does not
    write_slice(tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"x"\n')
    human, agent = run_cli('lint', tmp_path), run_cli('lint', tmp_path, '--toon')
    assert 'next:' in human.stdout
    assert 'next:' not in agent.stdout + agent.stderr   # clean payload end = nothing to fix
    # remediation hint (gate failure): both audiences; agent's on stderr, payload pure
    write_slice(tmp_path, GATE_SLICE)                   # canon depends on dropped -> error
    human, agent = run_cli('lint', tmp_path), run_cli('lint', tmp_path, '--toon')
    assert 'next:' in human.stdout
    assert 'next:' in agent.stderr and 'next:' not in agent.stdout


def test_jump_of_assembles_root_relative_location(tmp_path):
    (tmp_path / 'lib.py').write_text('BOOT_REPS = 1000\n')
    # file-scoped target: rg gives `line:content`, the target supplies the file
    loc, snip = jump_of('lib.py#BOOT_REPS', *resolve('lib.py#BOOT_REPS', tmp_path), tmp_path)
    assert loc == 'lib.py:1' and snip == 'BOOT_REPS = 1000'
    # bare symbol: rg gives an absolute `path:line:content` - normalized to root-relative
    loc, snip = jump_of('BOOT_REPS', *resolve('BOOT_REPS', tmp_path), tmp_path)
    assert loc == 'lib.py:1' and snip == 'BOOT_REPS = 1000'
    # non-OK: no location, evidence untouched
    loc, snip = jump_of('lib.py#GONE', *resolve('lib.py#GONE', tmp_path), tmp_path)
    assert loc == '' and snip is None
