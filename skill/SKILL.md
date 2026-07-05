---
name: keel
description: Use when iterating on a complex design captured as a keel graph (a TOON graph + bodies/), e.g. under .toons/**/*.graph.toon. Discussion is the default mode - brainstorm in conversation, edit the graph only once a decision is locked. Before editing a node, pack it for its 1-hop context; after any change, check it (graph lint + code-ref drift); diagnose drift/incompleteness with status; when asked "what next / what should I work on", answer with nextodo. Always edit the .toon graph, never the rendered output; write bodies/*.md prose only when the human explicitly asks.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py *), Bash(rg *)
---

# keel - iterate on a spec-as-graph without dropping connections

The canonical design lives in `*.graph.toon` (nodes + edges + invariants + decisions)
with prose in `bodies/<id>.md`. The rendered `spec.md` / views are BUILD OUTPUTS -
never hand-edit them; edit the graph and re-render. `view`/`watch` materialize those
previews as `*.view.md` files on disk - a live `keel watch` daemon and the human
own running those; never invoke them yourself.

Run the tools with (works from any working directory - no PATH, venv, or exec bit needed):

    python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py <cmd> ...

`${CLAUDE_SKILL_DIR}` is this skill's own dir and `scripts/` is the engine. Pure Python
stdlib plus ripgrep (`rg`) - nothing to install. (`keel <cmd> ...` also works when the
PATH shim is installed, a human convenience the skill does not rely on.)

The full grammar and a complete slice to copy live in `${CLAUDE_SKILL_DIR}/references/schema.md` -
read it BEFORE authoring or editing a slice; never reverse-engineer the format from the engine.

The container is `.toons/<slug>/` at the root of the crate/package it describes - that
root is `--code-root`, and `find` / `status` / `watch` all derive it by walking up to the
nearest `.toons/`. It is TRACKED: committed and versioned with the code, because it is the
source of truth you both re-render from and drift-check against. Never a scratchpad or an
untracked dir - that breaks `find`, `--code-root` defaulting, and `watch`, and a design
that cannot travel with its code cannot gate drift. Placement is determined, not a choice -
do not ask where to put it.

`--code-root` is the CODE root (your crate/package) for ref resolution, separate from the graph
dir. Every command also takes `--toon` (structured output), `--brief` (size-hinted
truncation of long lists/bodies - output is FULL by default), and `-h` (its own reference).

## Discuss first, write on lock
A design conversation has two modes, and the default is DISCUSSION. When the user proposes,
questions, or riffs, they are brainstorming WITH you - think it through and answer in
conversation. Do NOT edit the graph after every suggestion: a half-formed idea written as
structure is churn you will only unwrite. Reading is always fair game (`pack`/`status`/
`render`/`find`) - ground the discussion in what the graph already says.

The graph is written only when a decision LOCKS:
- the user says so ("lock it", "apply", "update the graph", ...), or
- the discussion has clearly converged: read the decision back in a line or two and get a yes.

The readback is the contract - what you write is exactly what was locked: the accepted
design (canon, or explore for a spike), the rejected alternatives (dropped, with the why),
and nothing that was not agreed. Batch everything locked in one discussion into ONE edit
pass, then `check`, then report what changed.

## Manual mode: bodies are written on request
`bodies/<id>.md` is the deep prose, and the most churn-prone part of the graph - so it is
created or edited ONLY when the human explicitly asks ("write up X", "expand that rationale").
A locked decision updates the `.toon` graph ALONE: the node's `card`, `state`, and edges carry
the verdict; the body waits. The graph stays the live, low-diff, authoritative record, and
each body becomes a deliberate artifact the human requests - not something re-written every
turn. When the prose has fallen behind the graph, say so and offer a body sync; do not silently
regenerate it. (The rendered `*.view.md` is build output either way - never hand-edited.)

## Measurements: an opt-in results sidecar (ask first, do not reflex)
Most graphs have NO measured results - keep numbers out of the model entirely. But an
EMPIRICAL design (experiments, benchmarks - findings that change every run and that
decisions/bodies cite by number) needs a home for them, and it is NOT the card: a card is
intent, and nothing drift-checks a number pasted into one, so it rots green while `check`
stays happy (`check`/`status` now WARN when a card outgrows a one-liner). That home is a
sibling `<slug>.results.toon` - its own file, so its churny diffs never touch the low-diff
graph, yet it unions like any slice so relations resolve. Shape: a
`result{id,touches,run,finding,data}` table keyed by the node it measures, with a `ref` to
the data artifact under `refs.numbers` so `check` at least existence-drifts the evidence.
The `finding` field is the earned number's ONE home - decisions/bodies cite it, never
re-paste it. This file is a GENERATED artifact the human owns: do NOT scaffold or
hand-maintain one speculatively. The family is narrow and easy to over-apply - when a graph
starts collecting measured numbers in cards, name the pattern and ASK before introducing it.

## The loop
The execution path for a LOCKED change:
1. **PICK** - `keel pack <node> <slices...>` - load ONLY this. It lists the node's
   attributes, its prose body, every edge touching it (the blast radius), the
   invariants/decisions that constrain it, and its `ref -> code` targets. pack is a SCALE
   tool: when the union is small (under ~40 nodes) just read the graph file - the point is
   loading one node's blast radius instead of the whole spec, however you get it.
   pack reads the GRAPH only, never code - so it takes NO `--code-root` (that flag is for
   the ref-resolving commands: `check` / `refs` / `status` / `new`).
2. **CLASSIFY** the change:
   - logic-only (a formula / impl detail) -> the graph is UNCHANGED (the ref still points)
   - structural (new node/edge, changed decision/invariant) -> edit the GRAPH FIRST
3. **IMPLEMENT** the code, plus the asserts that pin any new/changed invariant.
4. **RECONCILE** - point the node's `ref` edge at what you wrote: `ref,<node>,file.rs#symbol`.
5. **CHECK** - `keel check <slices...> --code-root <code>` - lint (graph-internal) + refs
   (graph<->code drift). Green, or fix and repeat.

## New ideas - explore, then keep or drop
Adding an idea is not committing to it - but even capturing one waits for a lock ("let's
try X" is a lock; a brainstormed maybe stays in conversation). Capture it as `state: explore`
(the node's `state` column), wired to its blast radius so you see what it touches - but held
to no rigor: `check` will not fail on an explore node whose `ref` points at throwaway spike
code. Then decide:
- **keep** -> set `state: canon` and reconcile its `ref`; now drift fails the gate and it
  renders into the spec.
- **drop** -> set `state: dropped` and put the short WHY in its `card` (the graph). Delete the
  spike freely - the dangling ref is expected, not drift. The node stays as "we tried X,
  rejected because Y". Its full-prose body (rationale + revival conditions) is written only if
  the human asks - see Manual mode.

`state` is a node's COMMITMENT (explore/canon/dropped, unset ≡ canon), separate from whether
it is built (the derived planned/implemented/drifted). Only canon nodes gate `check` and
render into the spec.

## Diagnose divergence
`keel status <slices...> --code-root <code>` - the dashboard: the canon/explore/dropped
lifecycle lanes, then over canon: implemented vs planned vs DRIFTED nodes, rule failures,
orphan nodes, and the unbuilt cross-slice seams (with who depends on each). Reach for this
when something feels off or before a big edit - it diagnoses; for "what should I do", see
nextodo below.

## What next - the derived worklist
`keel nextodo <slices...> --code-root <code>` answers ONE question: what is worth doing
right now. Drifted refs to FIX first, then READY nodes (planned canon whose prerequisites
are all implemented) ranked by leverage (frees = blocked nodes it is the last obstacle
for) and grouped into lanes - nodes in DIFFERENT lanes share no edge or constraint, so
they are safe to hand to parallel agents - then explore nodes awaiting a keep/drop
DECISION, then the BLOCKED list with each blocker named. Everything is derived from
edges + ref resolution: no plan files, no status columns, nothing to author or sync.
When the human asks "what next" / "where do I start", run THIS, not status - and pass
`--brief` (top of the ready list + counts) to keep your context lean; the full list is
the human's view. Scope it with `keel nextodo <goal-node> <slices...>`: the same ladder
restricted to the goal's unbuilt dependency cone - what stands between you and it.

## Rules of the model
- A reference is ALWAYS an edge (so lint catches a typo'd target); columns are literal
  attributes only.
- The graph owns intent/structure/decisions/invariants; code owns logic; the graph holds
  `ref -> code`, never a copy of the logic. A logic-only change touches no graph node.
- One node = anything referenced elsewhere. Prose that nothing references is a body, not a node.
- A node's `state` column is its COMMITMENT lane (explore/canon/dropped, unset ≡ canon),
  orthogonal to whether it is built. Only canon gates; a canon node must not depend on an
  explore/dropped one - but a symmetric kind (overlaps, shares, ...) is an ASSOCIATION,
  not a dependency: declare it `undirected` in rules rather than flipping the edge to
  appease lint.
- One fact, one place: a row cell is a one-liner for tables; the body owns the full
  rationale (and, for dropped nodes, the revival conditions); a decision card is a verdict
  plus its `touches` - never a restatement of what cells and bodies already say. A card is
  intent, NOT a lab notebook: measured numbers and run results never live in a card (nothing
  drift-checks one) - they go to `refs.numbers` data or a results sidecar (see Measurements).
- Model minimally: start at `id,state,card`; add a column only when a view needs it, an
  edge only when it changes a decision or a blast radius. Speculative structure is dead
  weight you re-sync forever.
- Never hand-edit rendered output.

The graph is the source. Starting from nothing? `keel find <path>` is the front door -
it reports which `.toons/` container (if any) already anchors that path, or a MISS. On a
MISS, `keel new <code-anchor>` scaffolds `.toons/<slug>/` with a skeleton slice - it
auto-detects and reuses an existing enclosing `.toons/` (placing a sibling slice) or creates
a fresh one at the code root, so calling `new` directly is usually enough without a prior
`find`. Do NOT hand-roll this discovery with raw shell (`find .toons -type f`, `head` on a
neighboring slice, `git log`/`git status`) - that duplicates what `find`/`new` already do,
and a sibling slice's content tells you nothing about where the new one goes. Then fill in
the nodes and edges (grammar: `references/schema.md`, above).
