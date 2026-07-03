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
