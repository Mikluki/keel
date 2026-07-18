# keel - a spec as a cacheable graph, not a wall of prose

A design doc starts true and rots: code moves, the doc doesn't, and handing the whole
thing to a coding agent burns context on prose that may no longer hold.

**keel** keeps a spec's durable *structure* - intent, decisions, invariants, and how
things reference each other - as a small graph, and pins the volatile parts (logic,
numbers) as `ref`s into the real code. The graph is a **cache**: a logic change leaves
it untouched, a structural change invalidates it, and a drift check tells you which
`ref`s went stale. An agent packs one node's 1-hop slice instead of the whole document;
the human-readable spec is *rendered* from the graph, never hand-edited.

The engine is **domain-agnostic** - it knows only `nodes`, `edges`, `views`, and
`rules`. What node/edge KINDS exist is declared as data in the `.toon` slices; the
engine contains no domain vocabulary. Everything is **agent-first**: commands speak
TOON for token-lean, drift-aware output.

## Layout

    engine/       the agnostic tool (pure Python stdlib, no domain words)
    skill/        the Claude Code skill source (SKILL.md + references/)
    completion/   _keel zsh tab-completion
    examples/     a self-contained toons/ repo that exercises the full engine
    deploy.sh     compose engine/ + skill/ -> ~/.claude/skills/keel/ (the install)

`engine/`, `skill/`, `completion/` are the **sources**; `deploy.sh` builds the install.
Never edit the deployed copy - change the source and re-run `./deploy.sh`.

## Run

Dev form is `python engine/cli.py <cmd>`; installed, that's just `keel <cmd>`.

    python engine/cli.py -h        # the command list (the source of truth)
    python engine/cli.py <cmd> -h  # one command's reference

The skill (`skill/SKILL.md`) teaches the working loop; day to day you drive keel through
it, not by hand. Requires Python 3.14 and ripgrep (`rg`, for graph<->code drift).

## Concepts

- **A container** is one concept's graph, living under `toons/<slug>/`. Map only the
  idea layer that needs focused attention, not the whole repo. The graph lives in a
  sibling `<repo>-keel/` worktree so code workers never trip over it.
- **A node** is anything referenced elsewhere; **an edge** is every reference (so a
  typo'd target is caught generically). A node's `state` is its commitment lane
  (`explore`/`canon`/`dropped`); its realization (`planned`/`implemented`/`drifted`) is
  *derived* from whether its `ref` resolves and cannot lie.

Full grammar: `skill/references/schema.md`.
