#!/usr/bin/env python3
"""new: scaffold a fresh .toons/<slug>/ container for a code anchor - the cold-start bootstrap.

Given the code your design will describe (a file or dir), compute its slug, create the
container in the right place (an existing enclosing .toons/, else <root>/.toons/), and seed a
minimal VALID slice you then edit. This is `find`'s MISS branch automated: no hand-mkdir, no
slug guessing, no format-guessing - lint/render/check pass on the skeleton as-is, so you edit
from a green baseline. Grammar to fill it in: references/schema.md.

    python new.py src/parser/lexer.rs --code-root ../my-crate      # -> .toons/src-parser-lexer/
    python new.py src/auth/ --code-root ../my-crate --toon          # structured body for an agent
"""
import sys
from pathlib import Path

import emit
import containers

# A minimal but COMPLETE slice: 2 nodes, a constraint, an edge, and the three views. It lints
# clean (unique ids, resolved edge/touches, no rules) and has 0 ref edges so `check` is green
# immediately; the agent replaces the example rows with the real design.
TEMPLATE = '''slice: {slug}
owns: TODO one line - the intent/structure this slice owns
refs: {{logic: {anchor}}}

nodes[2]{{id,card}}:
  example-a,"TODO replace - what this node is"
  example-b,"TODO replace - a second node"

invariants[1]{{id,touches,statement}}:
  inv-1,"example-a,example-b","TODO replace - a property that must hold across them"

edges[1]{{kind,from,to}}:
  relates,example-a,example-b

views[3]{{kind,title,table,arg,extra}}:
  table,Nodes,nodes,"id,card",
  join,Relations,nodes,relates,card
  entry,Node entry,nodes,,
'''


def main():
    args = emit.parse(sys.argv[1:], cmd='new')
    if not args.positional:
        emit.die('USAGE', 'new needs a code anchor: new <path> [--code-root <dir>]')
    anchor = args.positional[0]
    slug = containers.flatten(anchor)
    if not slug:
        emit.die('BAD_ANCHOR', f"cannot derive a slug from anchor {anchor!r} - pass a file or dir path")

    root = args.root or Path('.')
    toons = containers.find_toons_root(root) or (root / containers.TOONS_DIR)
    container = toons / slug
    if container.exists():
        emit.die('EXISTS', f"container already exists: {container} - edit it, do not re-scaffold",
                 exit_code=3)

    (container / 'bodies').mkdir(parents=True)
    slice_file = container / f"{slug}.graph.toon"
    slice_file.write_text(TEMPLATE.format(slug=slug, anchor=anchor))

    if args.toon:
        print(emit.toon(
            {'container': str(container), 'slug': slug, 'anchor': anchor, 'root': str(root)},
            {'created': (['path'], [{'path': str(slice_file)},
                                    {'path': str(container / 'bodies') + '/'}])}))
    else:
        print(f"scaffolded {container}/  (slug={slug}, anchor={anchor})")
        print(f"  {slice_file}")
        print(f"  {container}/bodies/   (drop <id>.md prose here)")
    emit.nxt(f"fill in {slice_file.name} (grammar: references/schema.md), "
             f"then keel check {container} --code-root {root}", toon=args.toon, guide=True)


if __name__ == '__main__':
    main()
