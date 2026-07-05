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
# nextodo: the derived worklist (ready/blocked/frees, lanes, goal cone)
# ============================================================================

NEXTODO_SLICE = '''slice: t
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


def _nextodo_dir(tmp_path, slice_text=NEXTODO_SLICE):
    (tmp_path / 'lib.py').write_text('def built(): pass\n')   # makes `base` implemented
    write_slice(tmp_path, slice_text)
    return tmp_path


def test_nextodo_ready_blocked_and_top_pick(tmp_path):
    d = _nextodo_dir(tmp_path)
    r = run_cli('nextodo', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'READY 1' in r.stdout and 'BLOCKED 1' in r.stdout
    assert '<- mid' in r.stdout                       # blocked `top`, with the why
    assert 'frees 1' in r.stdout                      # mid is top's last obstacle
    assert 'next: pack mid' in r.stdout               # the ranked pick, not `base` (built)


def test_nextodo_fix_ranks_before_ready(tmp_path):
    # a drifted ref outranks buildable work: the graph is lying, reconcile first
    d = _nextodo_dir(tmp_path, NEXTODO_SLICE
                     .replace('edges[3]', 'edges[4]')
                     .replace('  ref,base,lib.py\n', '  ref,base,lib.py\n  ref,top,gone.py\n'))
    r = run_cli('nextodo', d, '--code-root', d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'FIX 1' in r.stdout
    assert 'next: pack top' in r.stdout and 'reconcile' in r.stdout


def test_nextodo_goal_scopes_to_cone(tmp_path):
    d = _nextodo_dir(tmp_path)
    r = run_cli('nextodo', 'top', d, '--code-root', d, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['goal'] == 'top'
    assert [x['id'] for x in tables['ready']] == ['mid']
    assert tables['decide'] == []                     # spike is outside top's cone
    assert [x['id'] for x in tables['blocked']] == ['top']


def test_nextodo_goal_not_found(tmp_path):
    r = run_cli('nextodo', 'nosuch', _nextodo_dir(tmp_path))
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


def test_nextodo_lanes_from_coupling(tmp_path):
    # undirected `overlaps` is no prerequisite (all 4 stay ready) but it DOES couple
    # b1/b2 into one lane; the untouched a1/a2 each get their own parallel-safe lane
    write_slice(tmp_path, LANES_SLICE)
    r = run_cli('nextodo', tmp_path, '--toon')
    assert r.returncode == 0, r.stdout + r.stderr
    scalars, tables = parse_toon(r.stdout)
    assert scalars['ready'] == '4' and scalars['lanes'] == '3'
    lane = {x['id']: x['lane'] for x in tables['ready']}
    assert lane['b1'] == lane['b2']
    assert len({lane['a1'], lane['a2'], lane['b1']}) == 3


def test_nextodo_brief_clips_ready(tmp_path):
    rows = '\n'.join(f'  n{i},"card"' for i in range(6))
    write_slice(tmp_path, f'slice: t\nn[6]{{id,card}}:\n{rows}\n')
    full = run_cli('nextodo', tmp_path)
    brief = run_cli('nextodo', tmp_path, '--brief')
    assert 'n5' in full.stdout and 'drop --brief' not in full.stdout
    assert 'n5' not in brief.stdout and 'drop --brief' in brief.stdout


def test_nextodo_cycle_fails_loud(tmp_path):
    write_slice(tmp_path, 'slice: t\nn[2]{id,card}:\n  a,"x"\n  b,"y"\n\n'
                          'edges[2]{kind,from,to}:\n  needs,a,b\n  needs,b,a\n')
    r = run_cli('nextodo', tmp_path)
    assert r.returncode == 0
    assert 'READY 0' in r.stdout and 'cycle' in r.stdout
