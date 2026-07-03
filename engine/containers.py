#!/usr/bin/env python3
"""containers: the .toons/ repo-protocol core (slug<->anchor, discovery, reverse lookup).

A container is a graph dir at <repo-root>/.toons/<slug>/. The slug encodes the concept's
PRIMARY code anchor (`refs.logic`), so the mapping is reversible and lintable: given a
source file you can walk up to its container, and given a container you can check its dir
name still names its anchor. This module holds ONLY the pure path helpers - no output, no
argv, no domain vocabulary - shared by cli.py (slug shorthand), index.py (roll-up + slug
invariant), find.py (reverse lookup), and watch.py (the live monitor).

    flatten(anchor)            source path -> slug base ('/'->'-', source ext dropped)
    find_toons_root(start)     walk up to the enclosing <repo>/.toons dir (root = its parent)
    anchor_of(scalars)         a slice's refs.logic primary anchor
    iter_containers(toons)     the <slug>/ dirs under .toons/
    container_anchor(dir)      that container's primary anchor
    expected_slugs(anchors)    collision-aware slug per container (dec 1 fail / dec 2 -py/-rs)
    candidate_slugs(rel)       slugs that could anchor a source path, most specific first
    container_for_source(p)    reverse lookup: source path -> its anchoring container dir
    expand_slugs(argv, cmd)    cli sugar: a bare <slug> -> .toons/<slug>/ (+ --root)
"""
import re
from pathlib import Path, PurePosixPath

# ============================================================================
# CONFIG
# ============================================================================

SOURCE_EXTS = ('.py', '.rs')       # dropped from a slug by default; -> -py/-rs only on collision
TOONS_DIR = '.toons'
GRAPH_GLOB = '*.graph.toon'
INDEX_FILE = '_index.toon'
ROOT_CMDS = ('refs', 'status', 'check')   # commands whose --root should default to the repo root
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
# DISCOVERY (.toons/ tree)
# ============================================================================


def find_toons_root(start=None):
    """Walk up from `start` (default cwd) to the enclosing <repo>/.toons dir, or None.

    The repo root (== --root for ref resolution) is the returned dir's parent.
    """
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        cand = d / TOONS_DIR
        if cand.is_dir():
            return cand
    return None


def iter_containers(toons_root):
    """Every container dir under .toons/ (each is a graph dir); files like _index.toon are skipped."""
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
    """Reverse lookup: the .toons/<slug>/ dir anchoring `source`, or None (no toon yet).

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
    """A bare `<slug>` positional -> `.toons/<slug>/`, injecting `--root=<repo root>`.

    Only a token that names an existing .toons/<slug>/ dir AND is not an existing path in
    cwd is rewritten - an explicit path always wins, and node ids / file args never match.
    Injects --root for the code-resolving commands when the caller passed none. A no-op
    when there is no .toons/ (so running against a plain graph dir is unaffected).
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
    if hit and cmd in ROOT_CMDS and '--root' not in out:
        out += ['--root', str(toons.parent)]
    return out
