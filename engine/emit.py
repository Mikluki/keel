#!/usr/bin/env python3
"""emit: the shared agent-output layer every keel command routes through.

The engine consumes TOON but the commands were written to print for a human at a
terminal. This module carries the AXI principles so each command stays thin and they
all behave identically:

    parse(argv)          - split positionals from flags; fail loud on any unknown (P6)
    die(code, msg)       - structured error `error: CODE: message` to stderr, exit 2 (P6)
    toon(scalars, tables)- serialize a payload as TOON (round-trips render.parse_toon) (P1)
    head(items, n, noun) - size-hinted "N noun: a; b; c (+K more; --full)" list clip (P3)
    clip(text, n)        - size-hinted first-N-lines clip of a long body (P3)
    nxt(line)            - trailing `next: ...` contextual-disclosure hint (P9)

Count headers (P4) are the leading scalars of a payload; explicit "0 ..." empty states
(P5) are the caller's job but cheap once output is structured. stdout is PAYLOAD, stderr
is diagnostics/errors - never mix the two.
"""
import csv
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, Optional


# ---- shared CLI flag names (single source; consumed by parse + cli.strip_root + containers) ----
ROOT = '--code-root'        # the CODE root for ref resolution (your crate/package)
ROOT_SHORT = '-cc'          # shorthand for --code-root
ROOT_FLAGS = (ROOT, ROOT_SHORT)


@dataclass
class Args:
    positional: list = field(default_factory=list)
    root: Optional[Path] = None
    toon: bool = False
    full: bool = True      # output is FULL by default; --brief opts into size-hinted truncation
    extra: dict = field(default_factory=dict)   # opt-in per-command boolean flags (see `flags=`)


def parse(argv, *, allow_root=True, cmd='keel', flags=()):
    """Split argv into positionals + the known flags (--code-root [-cc], --toon, --full, --brief).

    Output is FULL by default; `--brief` opts into size-hinted truncation. `--full` is kept
    as an accepted no-op (back-compat / muscle memory). Any other `-flag` is fatal (P6):
    report it structurally and exit non-zero instead of silently swallowing it, which is how
    the old code lost typo'd flags. `flags` opts a command into extra boolean flags beyond the
    shared set; they land in `a.extra`.
    """
    a = Args(extra={f: False for f in flags})
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ROOT_FLAGS and allow_root:
            if i + 1 >= len(argv):
                die('BAD_FLAG', f"'{cmd}': {tok} needs a path argument")
            a.root = Path(argv[i + 1])
            i += 2
        elif tok == '--toon':
            a.toon = True
            i += 1
        elif tok == '--full':          # accepted no-op: full is the default now (back-compat)
            a.full = True
            i += 1
        elif tok == '--brief':         # opt IN to size-hinted truncation (the old default)
            a.full = False
            i += 1
        elif tok in a.extra:
            a.extra[tok] = True
            i += 1
        elif tok.startswith('-'):
            die('UNKNOWN_FLAG', f"'{cmd}': unknown flag {tok!r}")
        else:
            a.positional.append(tok)
            i += 1
    return a


def die(code, msg, *, exit_code=2) -> NoReturn:
    """Exit with a structured, greppable error an agent can branch on (P6).

    Exit-code taxonomy: 2 = usage error (bad flag/command/args); 3 = a valid call whose
    target or a required dependency is absent (node / .toons/ / ripgrep). Gate failures
    (lint/drift) exit 1 from their own command; 0 is success.
    """
    print(f"error: {code}: {msg}", file=sys.stderr)
    sys.exit(exit_code)


def default_root(root, paths):
    """The CODE root for ref resolution: the flag, else the first slice's dir."""
    if root is not None:
        return root
    return paths[0].parent if paths else Path('.')


# ---------------------------------------------------------------------------
# structured body (P1) + truncation (P3)
# ---------------------------------------------------------------------------

def _row(cols, r):
    buf = io.StringIO()
    csv.writer(buf, lineterminator='').writerow([str(r.get(c, '')) for c in cols])
    return buf.getvalue()


def toon(scalars, tables):
    """Serialize a payload as TOON: `key: value` scalars, then `name[N]{cols}:` tables.

    `scalars` is the count header (P4); `tables` maps name -> (cols, rows). An empty
    table still prints its `name[0]{cols}:` header, so 0-results are explicit (P5).
    Values must be single-line; long bodies belong in `scalars` as a file pointer.
    """
    out = [f"{k}: {v}" for k, v in scalars.items()]
    for name, (cols, rows) in tables.items():
        out.append(f"{name}[{len(rows)}]{{{','.join(cols)}}}:")
        out += ['  ' + _row(cols, r) for r in rows]
    return '\n'.join(out)


def head(items, n, noun, hint='--full'):
    """Count + first-n of a list with an escape hatch (generalizes drift's AMBIGUOUS).

    Use when the count is the headline (`2 defs: ...`); when the count is already in
    a surrounding header, prefer trunc_list to avoid printing it twice.
    """
    items = list(items)
    tail = f" (+{len(items) - n} more; {hint})" if len(items) > n else ''
    return f"{len(items)} {noun}: " + '; '.join(items[:n]) + tail


def trunc_list(items, n, *, full=False, sep=', ', hint='--full'):
    """Join an inline list, truncating past n with a size hint + escape hatch (P3)."""
    items = list(items)
    if full or len(items) <= n:
        return sep.join(items)
    return sep.join(items[:n]) + f"  (+{len(items) - n} more; {hint})"


def clip(text, n, hint):
    """First n lines of a long body + a size hint pointing at the escape hatch (P3)."""
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    return '\n'.join(lines[:n]) + f"\n... (+{len(lines) - n} lines; {hint})"


def nxt(line, *, toon=False, guide=False):
    """Append the relevant next-step command (P9 - for humans; failure-only for agents).

    Two species of hint: REMEDIATION (the output is a problem, the hint names the exit -
    drift, gate failures, misses) and tour GUIDE (guide=True: routine loop chaining -
    "now run drift", "context the top pick"). Agents (--toon) have the loop in their
    skill context and obediently follow imperative trailing lines, so guide hints are
    suppressed for them: an agent's success payload ends clean, only remediation earns
    a hint. Under --toon the stdout payload must stay pure (it round-trips parse_toon),
    so a surviving hint is a DIAGNOSTIC -> stderr. In human mode every hint is part of
    the readable view -> stdout, blank-line separated.
    """
    if toon:
        if not guide:
            print(f"next: {line}", file=sys.stderr)
    else:
        print(f"\nnext: {line}")
