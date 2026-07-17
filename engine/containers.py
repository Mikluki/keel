#!/usr/bin/env python3
"""containers: the toons/ repo-protocol core (slug<->anchor, discovery, reverse lookup).

A container is a graph dir at <repo-root>/toons/<slug>/. The slug encodes the concept's
PRIMARY code anchor (`refs.logic`), so the mapping is reversible and lintable: given a
source file you can walk up to its container, and given a container you can check its dir
name still names its anchor. This module holds the toons/ path helpers plus the one git query
that binds a graph to its code root - no output, no argv parsing, no domain vocabulary -
shared by cli.py (slug shorthand), index.py (roll-up + slug invariant), find.py (reverse
lookup), watch.py (the live monitor), and init.py (the split-repo bootstrap).

    flatten(anchor)            source path -> slug base ('/'->'-', source ext dropped)
    find_toons_root(start)     walk up to the enclosing <repo>/toons dir (root = its parent)
    git_worktrees(start)       git worktree list as (path, branch) pairs, main worktree first
    code_root_for(toons)       CODE root for a toons/: the main worktree if the graph is in a
                               linked (split-repo) worktree, else the graph's parent
    anchor_of(scalars)         a slice's refs.logic primary anchor
    iter_containers(toons)     the <slug>/ dirs under toons/
    container_anchor(dir)      that container's primary anchor
    expected_slugs(anchors)    collision-aware slug per container (dec 1 fail / dec 2 -py/-rs)
    candidate_slugs(rel)       slugs that could anchor a source path, most specific first
    container_for_source(p)    reverse lookup: source path -> its anchoring container dir
    expand_slugs(argv, cmd)    cli sugar: a bare <slug> -> toons/<slug>/ (+ --code-root)
    display_arg(tok)           hint sugar: a toons/<slug>/ path -> its bare <slug>
"""
import re
import subprocess
from pathlib import Path, PurePosixPath

import emit

# ============================================================================
# CONFIG
# ============================================================================

SOURCE_EXTS = ('.py', '.rs')       # dropped from a slug by default; -> -py/-rs only on collision
TOONS_DIR = 'toons'
GRAPH_GLOB = '*.graph.toon'
INDEX_FILE = '_index.toon'
ROOT_CMDS = ('drift', 'status', 'check', 'todo', 'matrix', 'context')   # commands whose --code-root should default to the repo root
KEEL_BRANCH = 'keel'               # the orphan branch the graph lives on (split-repo layout)
KEEL_WT_SUFFIX = '-keel'           # sibling worktree = <repo><suffix>/  (init's default target)
_LOGIC = re.compile(r'logic:\s*([^,}]+)')

# ============================================================================
# SLUG <-> ANCHOR (the naming rule)
# ============================================================================


def anchor_of(scalars):
    """A slice's PRIMARY code anchor = its `refs.logic` field (what render/status read too)."""
    m = _LOGIC.search(scalars.get('refs', ''))
    return m.group(1).strip() if m else ''


def flatten(anchor):
    """A source anchor path -> its slug BASE: drop a source ext, then '/' -> '-'.

        scripts/viz/lenses.py -> scripts-viz-lenses   (file anchor, ext dropped by default)
        scripts/viz           -> scripts-viz          (dir anchor)

    The -py/-rs disambiguation suffix (dec 2) is added by expected_slugs only when two
    anchors would otherwise flatten to the same base; an empty/absent anchor -> ''.
    """
    p = PurePosixPath(anchor.strip().strip('/'))
    if p.suffix in SOURCE_EXTS:
        p = p.with_suffix('')
    s = str(p)
    return s.replace('/', '-') if s not in ('.', '') else ''


def ext_suffix(anchor):
    """The disambiguation suffix for a file anchor ('py'/'rs'); '' for a dir/extensionless anchor."""
    suf = PurePosixPath(anchor.strip().strip('/')).suffix
    return suf[1:] if suf in SOURCE_EXTS else ''


def expected_slugs(anchors):
    """Map each container to its EXPECTED slug, applying the collision rule (dec 1/2).

    `anchors` is {container_name: anchor_path}. Returns {container_name: (slug, note)}:
      - unique base                 -> (base, '')                 ext dropped by default
      - base collision, exts differ -> (base-<ext>, '')           disambiguated (dec 2)
      - base collision, undisambig  -> (slug, 'COLLISION')        genuinely ambiguous (dec 1)
      - no/empty anchor             -> ('', 'NO_ANCHOR')
    """
    groups = {}
    for name, anchor in anchors.items():
        groups.setdefault(flatten(anchor), []).append(name)

    out = {}
    for base, members in groups.items():
        if not base:
            for name in members:
                out[name] = ('', 'NO_ANCHOR')
            continue
        if len(members) == 1:
            out[members[0]] = (base, '')
            continue
        # collision on the base slug: try to disambiguate each member by its source ext
        by_slug = {}
        for name in members:
            suf = ext_suffix(anchors[name])
            slug = f"{base}-{suf}" if suf else base
            by_slug.setdefault(slug, []).append(name)
        for slug, ns in by_slug.items():
            note = '' if len(ns) == 1 else 'COLLISION'
            for name in ns:
                out[name] = (slug, note)
    return out


# ============================================================================
# DISCOVERY (toons/ tree)
# ============================================================================


def find_toons_root(start=None):
    """Walk up from `start` (default cwd) to the enclosing <repo>/toons dir, or None.

    The repo root (== --code-root for ref resolution) is the returned dir's parent.
    """
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        cand = d / TOONS_DIR
        if cand.is_dir():
            return cand
    return None


def iter_containers(toons_root):
    """Every container dir under toons/ (each is a graph dir); files like _index.toon are skipped."""
    return sorted(d for d in Path(toons_root).iterdir() if d.is_dir())


def graph_slices(container):
    """The *.graph.toon slices in a container, name-sorted (the first is the primary)."""
    return sorted(Path(container).glob(GRAPH_GLOB))


def container_anchor(container):
    """A container's PRIMARY anchor: `refs.logic` of its first graph slice ('' if none).

    A container normally holds one graph slice; with several, the first (by name) is the
    primary - the concept's home that the slug encodes. Imported lazily to avoid pulling
    render into callers (like the cli slug sugar) that never read a slice.
    """
    from render import parse_toon
    for s in graph_slices(container):
        scalars, _ = parse_toon(s.read_text(), src=str(s))
        a = anchor_of(scalars)
        if a:
            return a
    return ''


# ============================================================================
# GIT WORKTREE TOPOLOGY (bind a graph to its code root)
# ============================================================================


def git_worktrees(start=None):
    """`git worktree list --porcelain` parsed to [(path, branch)], the MAIN worktree first.

    Returns [] when `start` is not inside a git repo, so a non-git graph dir (examples/, a
    tmp fixture) keeps the co-located default. `branch` is the short name ('keel') or None for
    a detached worktree. git always lists the main worktree first, then the linked ones.
    """
    try:
        r = subprocess.run(['git', '-C', str(start or Path.cwd()),
                            'worktree', 'list', '--porcelain'], capture_output=True, text=True)
    except OSError:
        return []
    if r.returncode != 0:
        return []
    out, path, branch = [], None, None
    for line in r.stdout.splitlines():
        if line.startswith('worktree '):
            if path is not None:
                out.append((path, branch))
            path, branch = Path(line[len('worktree '):]), None
        elif line.startswith('branch '):
            branch = line[len('branch '):].rsplit('/', 1)[-1]   # refs/heads/keel -> keel
    if path is not None:
        out.append((path, branch))
    return out


def code_root_for(toons_root):
    """The CODE root a toons/ resolves refs against: normally its parent, but the MAIN worktree
    when the graph lives in a LINKED worktree (the split-repo layout `keel init` sets up).

    git models exactly that relationship and lists the main worktree first, so this stays
    correct for the co-located case (parent IS the main worktree) and for a plain non-git graph
    dir (no worktrees -> parent). Only a graph sitting in a linked worktree is redirected.
    """
    parent = Path(toons_root).parent
    wts = git_worktrees(parent)
    if len(wts) >= 2 and parent.resolve() in {w[0].resolve() for w in wts[1:]}:
        return wts[0][0]                   # graph in a linked worktree -> code is in main
    return parent


# ============================================================================
# REVERSE LOOKUP (source file -> container)
# ============================================================================


def candidate_slugs(rel_source):
    """Slugs that could anchor a source path, most specific first: the file, then each parent dir.

    For a source file the exact (ext-dropped) slug is tried first, then its -py/-rs form
    (in case its container was disambiguated away from a same-named sibling), then the dir chain.
    """
    p = PurePosixPath(str(rel_source).strip('/'))
    cands = []
    if p.suffix in SOURCE_EXTS:
        base = flatten(str(p))
        cands += [base, f"{base}-{p.suffix[1:]}"]
    else:
        cands.append(flatten(str(p)))
    for parent in p.parents:
        s = str(parent)
        if s in ('.', ''):
            break
        cands.append(flatten(s))
    seen, uniq = set(), []
    for c in cands:                        # keep order, drop dups/empties
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def container_for_source(source, toons_root=None):
    """Reverse lookup: the toons/<slug>/ dir anchoring `source`, or None (no toon yet).

    Walks the source path from most specific (the file) up its parent dirs, returning the
    first existing container. `source` may be absolute or relative to the repo root.
    """
    src = Path(source)
    if toons_root is None:
        toons_root = find_toons_root(src.parent if src.is_absolute() else None)
    if toons_root is None:
        return None
    repo_root = Path(toons_root).parent
    if src.is_absolute():
        try:
            rel = src.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return None                    # source lives outside this repo
    else:
        rel = Path(source)
    for slug in candidate_slugs(rel):
        cand = Path(toons_root) / slug
        if cand.is_dir():
            return cand
    return None


# ============================================================================
# CLI SUGAR (<slug> shorthand)
# ============================================================================


def expand_slugs(argv, cmd):
    """A bare `<slug>` positional -> `toons/<slug>/`, injecting `--code-root=<code root>`.

    Only a token that names an existing toons/<slug>/ dir AND is not an existing path in
    cwd is rewritten - an explicit path always wins, and node ids / file args never match.
    Injects --code-root for the code-resolving commands when the caller passed none, via
    code_root_for so a split-repo graph resolves against the main worktree, not its own empty
    parent. A no-op when there is no toons/ (so running against a plain graph dir is unaffected).
    """
    toons = find_toons_root()
    if toons is None:
        return argv
    out, hit = [], False
    for tok in argv:
        if (not tok.startswith('-') and '/' not in tok
                and (toons / tok).is_dir() and not Path(tok).exists()):
            out.append(str(toons / tok))
            hit = True
        else:
            out.append(tok)
    if hit and cmd in ROOT_CMDS and not any(f in out for f in emit.ROOT_FLAGS):
        out += [emit.ROOT, str(code_root_for(toons))]
    return out


def display_arg(tok):
    """expand_slugs in reverse, for `next:` hints: a container-dir path compresses back to
    the bare <slug> the human typed (which the shorthand re-expands on the next call);
    anything else passes through untouched."""
    p = Path(tok)
    return p.name if p.is_dir() and p.parent.name == TOONS_DIR else tok
