#!/usr/bin/env python3
"""find: the front door - which .toons/ container anchors a source file you're about to edit.

Given a path you are about to touch, flatten it and walk up its parent dirs to the first
anchoring container, then print that container so you can enter its loop. A MISS is not an
error - it is the bootstrap signal: no toon covers this code yet, so `mkdir .toons/<slug>/`
and seed a slice. The reverse of the naming rule that index.py enforces.

    python find.py scripts/viz/lenses.py         # -> .toons/scripts-viz-lenses (+ next: check)
    python find.py src/parser/lexer.rs --toon     # structured body for an agent
"""
import sys
from pathlib import Path

import emit
import containers


def main():
    args = emit.parse(sys.argv[1:], allow_root=False, cmd='find')
    if not args.positional:
        emit.die('USAGE', 'find needs a source path: find <path>')
    source = args.positional[0]

    src = Path(source)
    toons = containers.find_toons_root(src.parent if src.is_absolute() else None)
    if toons is None:
        emit.die('NO_TOONS', 'no .toons/ dir found by walking up from the source path', exit_code=3)
    repo_root = toons.parent

    container = containers.container_for_source(source, toons)
    rel = _rel_to_repo(src, repo_root)
    cands = containers.candidate_slugs(rel)

    if args.toon:
        print(emit.toon(
            {'source': source, 'anchored': 'yes' if container else 'no', 'root': repo_root,
             'container': str(container) if container else '(none)',
             'slug': container.name if container else ''},
            {'candidates': (['slug'], [{'slug': c} for c in cands])}))
    else:
        if container:
            print(f"{source}  ->  {container}   (slug={container.name})")
        else:
            print(f"{source}  ->  0 - no container anchors this file yet")
            print(f"  candidate slugs (most specific first): "
                  f"{emit.trunc_list(cands, 6, full=args.full)}")

    if container:
        emit.nxt(f"keel check {container.name}   # open this container's loop (PICK/CHECK)",
                 toon=args.toon)
    else:
        top = cands[0] if cands else 'the-concept'
        emit.nxt(f"bootstrap: mkdir .toons/{top}/ and seed <name>.graph.toon "
                 f"with refs: {{logic: {rel}}}", toon=args.toon)


def _rel_to_repo(src, repo_root):
    """The source path relative to the repo root (for candidate slugs + the bootstrap hint)."""
    if src.is_absolute():
        try:
            return src.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return src
    return src


if __name__ == '__main__':
    main()
