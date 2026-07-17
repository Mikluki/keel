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
import containers
from drift import jump_of, resolve
from render import load_union, parse_toon, weight_summary

ENGINE = Path(__file__).resolve().parent.parent / 'engine'


# ============================================================================
# FUNCTIONS
# ============================================================================

def run_cli(cmd, *args, cwd=None):
    """Run `cli.py <cmd> <args...>` exactly as an agent would; return the result.

    `cwd` sets the working dir the command sees (init/find/slug-shorthand are cwd-relative).
    """
    return subprocess.run([sys.executable, str(ENGINE / 'cli.py'), cmd, *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


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
# prose-cell-length warning: soft, non-gating, every NON-reserved cell
# ============================================================================

def test_long_cell_warns_but_does_not_gate(tmp_path):
    long = 'x' * 250
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{long}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr        # a prose cell is a smell, not an error
    assert '1 warnings' in r.stdout                        # counted on the summary line (watch reads it)
    assert 'a' in r.stdout and 'chars' in r.stdout


def test_short_cell_no_warning(tmp_path):
    r = run_cli('lint', write_slice(tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"short"\n'))
    assert r.returncode == 0
    assert '0 warnings' in r.stdout


def test_long_cell_with_body_flags_split(tmp_path):
    # a long cell that ALSO has a body = the same rationale in two places
    (tmp_path / 'bodies').mkdir()
    (tmp_path / 'bodies' / 'a.md').write_text('# a\nprose')
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{"y" * 250}"\n'))
    assert r.returncode == 0
    assert 'also has a body' in r.stdout


def test_long_why_on_decision_warns(tmp_path):
    # generalization off `card`: the decisions table has NO `card` column - its prose lives in
    # why/chose/rejected, and any non-reserved cell over the limit must still warn
    long = 'w' * 250
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\ndecisions[1]{{id,why}}:\n  d1,"{long}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '1 warnings' in r.stdout
    assert 'd1' in r.stdout and 'why' in r.stdout          # the offending column is named


def test_two_long_cells_on_one_row_count_twice(tmp_path):
    # the count is per-CELL, not per-node: one decision with two prose columns over the limit
    # trips twice
    long = 'q' * 250
    r = run_cli('lint', write_slice(
        tmp_path, f'slice: t\ndecisions[1]{{id,chose,rejected}}:\n  d1,"{long}","{long}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '2 warnings' in r.stdout
    assert 'chose' in r.stdout and 'rejected' in r.stdout


def test_long_finding_in_results_is_exempt(tmp_path):
    # a result's `finding` is the earned home for a measured number: the whole measurement row
    # (the `finding`+`touches` shape, the SAME predicate as measured_ids) is EXEMPT from the
    # cell check, even at full length - the sidecar is where churny numbers live
    (tmp_path / 'g.graph.toon').write_text('slice: t\nn[1]{id,card}:\n  exp,"an experiment"\n')
    (tmp_path / 'g.results.toon').write_text(
        f'slice: t-res\nresult[1]{{id,touches,run,finding,data}}:\n'
        f'  r-exp,exp,run7,"{"z" * 300}",refs.numbers#R7\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '0 warnings' in r.stdout


def test_long_touches_value_is_reserved(tmp_path):
    # `touches` is a RESERVED (structural) column - a long touches list is never prose, so it
    # must not warn even past the limit
    long = 'x' * 250
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\ninv[1]{{id,touches}}:\n  a,"{long}"\n'))
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
# prose-cell HARD gate: a canon cell grown into a body fails check (exit 1)
# ============================================================================

def test_canon_cell_over_hard_limit_gates_check(tmp_path):
    # L2 (3000): a cell this long is a body pasted into a table cell - no honest reading is left,
    # so it is a HARD error (exit 1), not a soft smell. A bare node (no state) is canon.
    big = 'x' * 3100
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{big}"\n'))
    assert r.returncode != 0, r.stdout + r.stderr
    assert 'a.card' in r.stdout                            # the error names the offending cell+col
    assert 'body in a cell' in r.stdout


def test_canon_cell_between_limits_warns_only(tmp_path):
    # between L1 (200) and L2 (3000): past a one-liner (soft warn) but not yet a body - it must
    # NOT hard-fail, so the two tiers stay distinct
    mid = 'x' * 300
    r = run_cli('lint', write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{mid}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '1 warnings' in r.stdout                        # soft tier still fires
    assert 'errors: 0' in r.stdout                         # ... but no hard error


def test_dropped_cell_over_hard_limit_warns_not_gates(tmp_path):
    # the hard tier is CANON-only: a dropped node still earns the soft warn (nothing is invisible)
    # but must not gate check - a rejected idea is not held to the shipping bar
    big = 'y' * 3100
    r = run_cli('lint', write_slice(
        tmp_path, f'slice: t\nn[1]{{id,state,card}}:\n  a,dropped,"{big}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '1 warnings' in r.stdout                        # soft tier fires for every state
    assert 'errors: 0' in r.stdout


def test_explore_cell_over_hard_limit_does_not_gate(tmp_path):
    # explore is provisional - also exempt from the hard gate (it still gets the soft warn)
    big = 'z' * 3100
    r = run_cli('lint', write_slice(
        tmp_path, f'slice: t\nn[1]{{id,state,card}}:\n  a,explore,"{big}"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'errors: 0' in r.stdout


def test_measurement_finding_over_hard_limit_is_exempt(tmp_path):
    # the measurement-row carve-out holds at the hard tier too: a long `finding` (the
    # finding+touches shape, the SAME predicate as measured_ids) is the sidecar's earned home
    # for a number, never a gated cell
    (tmp_path / 'g.graph.toon').write_text('slice: t\nn[1]{id,card}:\n  exp,"an experiment"\n')
    (tmp_path / 'g.results.toon').write_text(
        f'slice: t-res\nresult[1]{{id,touches,run,finding,data}}:\n'
        f'  r-exp,exp,run7,"{"z" * 3100}",refs.numbers#R7\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'errors: 0' in r.stdout


# ============================================================================
# leaked numbers: a measured value stranded in prose (no drift-checked home)
# ============================================================================

def test_number_in_prose_cell_leaks(tmp_path):
    # a measured number pasted into a card on a node with NO ref and NO finding has no
    # drift-checked home - it rots green, so it is flagged (soft, non-gating)
    r = run_cli('lint', write_slice(
        tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"KL falls 4.75 nats"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks (1)' in r.stdout
    assert '4.75' in r.stdout and 'card' in r.stdout    # the matched token + column are named


def test_number_on_refd_node_does_not_leak(tmp_path):
    # exempt-if-ref: a node with a `ref` edge already has a drift-checked home, so its number
    # is not flagged - a deliberate trade to keep the warning credible
    r = run_cli('lint', write_slice(
        tmp_path,
        'slice: t\nn[1]{id,card}:\n  a,"KL falls 4.75 nats"\n\n'
        'edges[1]{kind,from,to}:\n  ref,a,mod.py#KL\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks: 0' in r.stdout


def test_number_on_measured_node_does_not_leak(tmp_path):
    # a node some finding row `touches` is measured (measured_ids) - the sidecar is the number's
    # home, so a value in its card is not a leak
    (tmp_path / 'g.graph.toon').write_text(
        'slice: t\nn[1]{id,card}:\n  a,"KL falls 4.75 nats"\n')
    (tmp_path / 'g.results.toon').write_text(
        'slice: t-res\nresult[1]{id,touches,finding}:\n  r-a,a,"KL = 4.75 nats"\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks: 0' in r.stdout


def test_measurement_row_finding_number_is_exempt(tmp_path):
    # the measurement row itself (finding+touches) is where numbers correctly live - its own
    # `finding` value is never a leak
    (tmp_path / 'g.graph.toon').write_text('slice: t\nn[1]{id,card}:\n  exp,"an experiment"\n')
    (tmp_path / 'g.results.toon').write_text(
        'slice: t-res\nresult[1]{id,touches,finding}:\n  r-exp,exp,"KL falls 4.75 nats"\n')
    r = run_cli('lint', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks: 0' in r.stdout


def test_bare_integer_does_not_leak(tmp_path):
    # bare integers are NOT flagged - _NUM_LEAK matches only empirical shapes (decimals, ratios,
    # sci-notation, ~/±); bare-int matching is where false positives explode
    r = run_cli('lint', write_slice(
        tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"pinned at 25"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks: 0' in r.stdout


def test_leak_is_warn_only_never_gates(tmp_path):
    # warn-only: even a clear leak (a ratio, in a `why` cell - generalized off card) keeps check
    # green; a heuristic must never gate
    r = run_cli('lint', write_slice(
        tmp_path, 'slice: t\nn[1]{id,why}:\n  a,"measured 13/20 runs converged"\n'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'leaks (1)' in r.stdout
    assert '13/20' in r.stdout


# ============================================================================
# weight axis: WEIGHT rolled up once, reported apart from WIRING (kill the false-green)
# ============================================================================

def test_weight_summary_rolls_up_the_axis(tmp_path):
    # one dict aggregating A/B/C, single-sourced for status AND index: a split-brain cell (a
    # long card that ALSO has a body), a leaked ratio, and a long why
    card_sb, why_sb = 'x' * 250, 'short'
    card_lk, why_lk = 'measured 13/20 runs', 'w' * 250
    (tmp_path / 'bodies').mkdir()
    (tmp_path / 'bodies' / 'sb.md').write_text('# sb\nrationale lives here too\n')
    write_slice(tmp_path, 'slice: t\nn[2]{id,card,why}:\n'
                          f'  sb,"{card_sb}","{why_sb}"\n'
                          f'  lk,"{card_lk}","{why_lk}"\n')
    slices, tables, prov = load_union([tmp_path / 'fix.graph.toon'])
    w = weight_summary(tables, slices, prov)
    assert w['over_soft'] == 2          # sb.card and lk.why both past CELL_MAX
    assert w['over_hard'] == 0          # neither reaches the hard tier
    assert w['leaked'] == 1             # the 13/20 ratio, unref'd + unmeasured
    assert w['split_brain'] == 1        # sb is long AND has a body; lk (no body) is not
    assert w['prose_chars'] == len(card_sb) + len(why_sb) + len(card_lk) + len(why_lk)


def test_status_reports_weight_axis_and_verdict(tmp_path):
    # wiring clean (the node's ref resolves) but a cell is heavy: the WEIGHT section carries the
    # count and the terminal verdict is the weight branch, never a wiring-only all-clear
    (tmp_path / 'lib.py').write_text('def built(): pass\n')
    write_slice(tmp_path, f'slice: t\nn[1]{{id,card}}:\n  a,"{"x" * 250}"\n\n'
                          'edges[1]{kind,from,to}:\n  ref,a,lib.py\n')
    r = run_cli('status', tmp_path, '--code-root', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'WEIGHT (prose rot)' in r.stdout             # the axis is its own section
    assert 'over soft    1' in r.stdout                 # with the count
    assert 'wiring clean; WEIGHT' in r.stdout           # verdict names the second axis
    assert 'all canon nodes implemented' not in r.stdout  # the old false-green is gone


def test_status_clean_on_both_axes(tmp_path):
    # short cell, ref resolves -> the verdict clears BOTH axes explicitly (not just wiring)
    (tmp_path / 'lib.py').write_text('def built(): pass\n')
    write_slice(tmp_path, 'slice: t\nn[1]{id,card}:\n  a,"short"\n\n'
                          'edges[1]{kind,from,to}:\n  ref,a,lib.py\n')
    r = run_cli('status', tmp_path, '--code-root', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'clean on both axes' in r.stdout


def test_index_rollup_shows_weight(tmp_path):
    # the repo board carries weight too: a per-container `Nw` figure and a repo total, so an
    # obese container is visible in the roll-up (slug 'lib' == flatten('lib.py'), no violation)
    cont = tmp_path / 'toons' / 'lib'
    cont.mkdir(parents=True)
    (cont / 'lib.graph.toon').write_text(
        f'slice: t\nrefs: logic: lib.py\nn[1]{{id,card}}:\n  a,"{"x" * 250}"\n')
    r = run_cli('index', tmp_path / 'toons', '--check')
    assert r.returncode == 0, r.stdout + r.stderr
    assert '1w' in r.stdout                             # per-container weight figure
    assert 'weight      1' in r.stdout                  # repo total line


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
    # hints print the human-typeable form: a toons/<slug>/ path arg compresses back to
    # the bare slug, slices-first - exactly what the shorthand re-expands on the next call
    cont = tmp_path / 'toons' / 'demo'
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


# ============================================================================
# context: the node-SET selector (induced subgraph of `[table:]col=val`)
# ============================================================================

SET_SLICE = '''slice: t
metric[3]{id,tier,state,card}:
  m-a,B,canon,"first B, canon"
  m-b,B,explore,"second B, explore"
  m-c,A,canon,"an A metric, different tier"

gear[1]{id,state,card}:
  g,canon,"outside the tier"

edges[4]{kind,from,to}:
  hardens,m-a,m-b
  measures,g,m-a
  ref,m-a,lib.py#K
  ref,m-b,lib.py#K

decision[1]{id,touches,statement}:
  D-x,"m-a,m-b","both B share this decision"
'''


def _set_dir(tmp_path):
    (tmp_path / 'lib.py').write_text('K = 7\n')
    write_slice(tmp_path, SET_SLICE)
    return tmp_path


def test_context_selector_induced_subgraph(tmp_path):
    # a class ask enumerates from the tier column - including the explore member a
    # guess-and-loop would drop; the intra-set edge is internal, the outside edge a seam
    d = _set_dir(tmp_path)
    r = run_cli('context', 'metric:tier=B', d, '--code-root', d, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['selector'] == 'metric:tier=B' and scalars['nodes'] == '2'
    assert {m['id'] for m in tables['members']} == {'m-a', 'm-b'}
    assert tables['internal'] == [{'kind': 'hardens', 'from': 'm-a', 'to': 'm-b'}]
    assert tables['boundary'] == [{'dir': 'in', 'kind': 'measures',
                                   'member': 'm-a', 'other': 'g'}]


def test_context_selector_constraint_once_with_members(tmp_path):
    # a decision touching two members is listed ONCE, naming which - not re-printed per node
    _, tables = parse_toon(run_cli('context', 'metric:tier=B', _set_dir(tmp_path),
                                   '--toon').stdout)
    assert len(tables['constraints']) == 1
    assert tables['constraints'][0]['id'] == 'D-x'
    assert tables['constraints'][0]['touches'] == 'm-a m-b'


def test_context_selector_refs_dedupe_by_target(tmp_path):
    # m-a and m-b both ref lib.py#K -> ONE code row, both owners, resolved once
    d = _set_dir(tmp_path)
    scalars, tables = parse_toon(run_cli('context', 'metric:tier=B', d,
                                         '--code-root', d, '--toon').stdout)
    assert scalars['refs'] == '1' and len(tables['code']) == 1
    assert tables['code'][0]['target'] == 'lib.py#K'
    assert tables['code'][0]['member'] == 'm-a m-b'
    assert tables['code'][0]['status'] == 'OK' and 'K = 7' in tables['code'][0]['evidence']


def test_context_selector_state_default_matches_unset(tmp_path):
    # `state=canon` must catch nodes with NO state column (unset =~ canon) - the same
    # completeness the set query exists to guarantee
    write_slice(tmp_path, 'slice: t\nn[2]{id,card}:\n  a,"no state col"\n  b,"also unset"\n')
    scalars, tables = parse_toon(run_cli('context', 'state=canon', tmp_path, '--toon').stdout)
    assert scalars['nodes'] == '2'
    assert {m['id'] for m in tables['members']} == {'a', 'b'}


def test_context_selector_bare_col_scans_all_tables(tmp_path):
    # unscoped `tier=B` finds the B metrics without naming their home table
    scalars, _ = parse_toon(run_cli('context', 'tier=B', _set_dir(tmp_path), '--toon').stdout)
    assert scalars['nodes'] == '2'


def test_context_selector_no_match_dies_loud(tmp_path):
    r = run_cli('context', 'metric:tier=Z', _set_dir(tmp_path))
    assert r.returncode == 3
    assert 'NO_MATCH' in r.stderr and 'tier=' in r.stderr


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


# ============================================================================
# init + worktree topology: the split-repo bootstrap and code-root binding
# ============================================================================

def _git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True)


def _make_repo(tmp_path):
    """A minimal committed git repo at tmp_path/proj (so its sibling worktree is proj-keel)."""
    repo = tmp_path / 'proj'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    (repo / 'src.py').write_text('K = 1\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'init')
    return repo


def _branch(wt):
    return subprocess.run(['git', '-C', str(wt), 'symbolic-ref', '--short', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def test_git_worktrees_and_code_root_non_git(tmp_path):
    # a graph dir outside any git repo keeps the co-located default (parent), never crashes
    (tmp_path / 'toons').mkdir()
    assert containers.git_worktrees(tmp_path) == []
    assert containers.code_root_for(tmp_path / 'toons') == tmp_path


def test_code_root_for_colocated_is_parent(tmp_path):
    # a toons/ in the MAIN worktree resolves refs against that worktree - unchanged behavior
    repo = _make_repo(tmp_path)
    (repo / 'toons').mkdir()
    assert containers.code_root_for(repo / 'toons').resolve() == repo.resolve()


def test_init_creates_orphan_worktree(tmp_path):
    repo = _make_repo(tmp_path)
    r = run_cli('init', cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    wt = repo.parent / 'proj-keel'
    assert wt.is_dir() and (wt / 'toons').is_dir() and (wt / '.gitignore').exists()
    assert _branch(wt) == 'keel'
    assert not (repo / 'toons').exists()          # the graph is NOT on disk in the code tree


def test_init_binds_code_root_to_main_worktree(tmp_path):
    # the payoff: from the split worktree, code_root_for points back at the code, not its own dir
    repo = _make_repo(tmp_path)
    run_cli('init', cwd=repo)
    wt = repo.parent / 'proj-keel'
    assert containers.code_root_for(wt / 'toons').resolve() == repo.resolve()


def test_init_is_idempotent(tmp_path):
    repo = _make_repo(tmp_path)
    run_cli('init', cwd=repo)
    r = run_cli('init', cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'present' in r.stdout


def test_init_reattaches_existing_branch(tmp_path):
    repo = _make_repo(tmp_path)
    run_cli('init', cwd=repo)
    wt = repo.parent / 'proj-keel'
    _git(repo, 'worktree', 'remove', '--force', str(wt))   # branch keel survives, worktree gone
    r = run_cli('init', cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'attached' in r.stdout and _branch(wt) == 'keel'


def test_init_refuses_target_inside_code_tree(tmp_path):
    repo = _make_repo(tmp_path)
    r = run_cli('init', repo / 'inside', cwd=repo)
    assert r.returncode == 2 and 'NESTED' in r.stderr


def test_init_outside_git_dies_loud(tmp_path):
    r = run_cli('init', cwd=tmp_path)              # tmp_path is not a git repo
    assert r.returncode == 2 and 'NO_REPO' in r.stderr
