# keel - a spec as a cacheable graph, not a wall of prose

A design doc starts true and rots: code moves, the doc doesn't, and handing the whole
thing to a coding agent burns context on prose that may no longer hold - with no way to
see which lines are still the source of truth.

**keel** keeps a spec's durable *structure* - intent, decisions, invariants, and how
things reference each other - as a small graph, and pins the volatile parts (logic,
numbers) as `ref`s into the real code. The graph is a cache: a logic change leaves it
untouched, a structural change invalidates it, and `check` tells you which drifted. An
agent packs one node's 1-hop slice instead of the whole document; the human-readable
spec is *rendered* from the graph, never hand-edited. Built agent-first - every command
speaks TOON and the [10 AXI principles](#agent-facing-output-the-10-axi-principles) for
token-lean, drift-aware output.

A **domain-agnostic** engine: it knows only `nodes` (rows with an `id`), `edges`,
`views`, and `rules`. What node/edge KINDS exist and which VIEWS to draw are declared
as data in the `.toon` slices - the engine contains no domain vocabulary. Edit the
graph; the human spec/views are rendered from it (never hand-edited).

## Contents

- [Principles](#principles)
  - [SSOT lifecycle](#ssot-lifecycle---one-truth-a-disposable-seed)
  - [Node lifecycle](#node-lifecycle---two-axes-add-explore-then-decide)
  - [Agent-facing output (the 10 AXI principles)](#agent-facing-output-the-10-axi-principles)
- [Layout](#layout)
- [Run](#run)
- [Containers](#containers---where-toons-live-in-a-large-repo)
- [Modeling rules](#modeling-rules)
- [Proof it is algorithm-agnostic](#proof-it-is-algorithm-agnostic)

# Principles

## SSOT lifecycle - one truth, a disposable seed
A design `.md` is fuel, not truth: burned once at init, then archived.

    design.md ─absorb─► toon ─scaffold─► code
     (frozen seed)      (cache)          (SSOT)

- **Volatility gradient** (inverse of abstraction): `code >> toon >> design.md`.
  Code churns; the toon is a higher-abstraction *cache of the code's relational
  structure*; the design.md never changes again.
- **Invalidation by change KIND**: a logic/number change leaves the toon untouched
  (its `ref` still points); a structural change (new node/edge, changed decision or
  invariant) invalidates it. `drift` is the staleness detector.
- **SSOT hands off once**: the toon is SSOT only in the window before code exists
  (unresolved `ref -> code` are listed, not failed); the moment code lands, code is
  SSOT permanently.

## Node lifecycle - two axes, add-explore-then-decide
A node carries two orthogonal states so "am I keeping this?" never gets confused with
"is it built?":

- **Realization (DERIVED, never hand-written)** - `planned` / `implemented` / `drifted`,
  computed by `status.classify` from whether the node's `ref` resolves. It cannot lie.
- **Commitment (DECLARED - a literal `state` attribute; unset ≡ `canon`)** - `explore`
  (provisional, under evaluation), `canon` (accepted design), `dropped` (explored then
  rejected, kept as a record + the why). See `render.state_of`.

The add/explore/decide order:

    capture ─► explore ──┬─► keep ─► canon ─► [planned → implemented → drifted]
    (state:explore)      └─► drop ─► dropped   (+ write the why; the spike ref may dangle)

`state` is real because it gates behavior, not just labels: `drift`/`check` fail only on
`canon` drift (explore/dropped refs are muted - spike and delete freely); `status`/`index`
bucket the three lanes and compute health over canon; `render` shows every node but groups
the bodies appendix by state (`# Canon`/`# Explore`/`# Dropped`, rejected last); and `lint`
fails a canon node that depends on an explore/dropped one (you pulled the rug) or a typo'd
`state` value.

## Agent-facing output (the 10 AXI principles)
Design targets for the CLI, now met. The shared `emit` helper carries 1+3+4+5+9 (TOON
body, size-hinted truncation, count header, explicit empty states, trailing `next:`); 6
and 10 are argument-layer fixes in `cli.py`; 7 is the opt-in `watch` monitor.

1. **Token-efficient output** - TOON format for ~40% token savings over JSON.
   - [x] `--toon` on every command via `emit.toon` (round-trips `render.parse_toon`).
2. **Minimal default schemas** - 3-4 fields per list item, not 10+.  (ok; render `entry`=6 widest)
3. **Content truncation** - truncate large text fields with size hints and escape hatches.
   - [x] `emit.clip`/`head`/`trunc_list` truncate bodies + long lists with a size hint and
     a `--full` escape hatch (generalizes drift's AMBIGUOUS count+head).
4. **Pre-computed aggregates** - counts and statuses that eliminate round trips.  (ok in `status`)
   - [x] `context` header tallies edges/constraints/refs; counts lead every `--toon` body.
5. **Definitive empty states** - explicit "0 results", never ambiguous empty output.
   - [x] Every section prints an explicit "0 ..." state (`context` sections, `status` SEAMS,
     and `name[0]{...}` empty tables in `--toon`).
6. **Structured errors & exit codes** - idempotent mutations, structured errors, no
   interactive prompts, fail loud on unknown flags.
   - [x] `emit.parse` validates flags per command, exiting 2 on any unknown flag.
   - [x] `emit.die` gives errors a stable `error: CODE: message` shape; exit codes: 2 usage,
     3 target/dependency absent (node / .toons / ripgrep), 1 a failed gate.
7. **Ambient context** - offer opt-in ambient integration, with the skill as the on-demand path.
   - [x] `cli.py watch` runs a decoupled poll-monitor over `.toons/` (refresh previews + lint
     on change, maintain `_watch.status`); it never interrupts the agent, which pulls
     `check`/`status` on its own schedule. Skill stays the on-demand path.
8. **Content first** - show actual data, not a wall of help text.  (ok)
9. **Contextual disclosure** - append relevant next-step commands after output, not all
   upfront.
   - [x] Every command ends with a `next:` line via `emit.nxt` (`status`->fix drift or the
     todo worklist; `context`->edit then check; failing `check`->the fix). Hints split by
     audience: humans get the full ladder (remediation + tour-guide); agents (`--toon`) get
     remediation only (drift/failures/misses, on stderr so the payload round-trips
     `parse_toon`) - a routine hint repeated to an agent is duplicate tokens plus an
     obedience nudge, and its success payloads end clean.
10. **Consistent help** - concise per-subcommand reference for when agents need it.
    - [x] `<cmd> -h/--help` prints that module's docstring (via `cli.py docstring`).

# Layout
    skill/         the Claude skill SOURCE (composed into the install by deploy.sh)
      SKILL.md       teaches the loop; invokes ${CLAUDE_SKILL_DIR}/scripts/cli.py
      references/    schema.md - the full TOON graph grammar reference
    deploy.sh      install skill/ + engine/ -> ~/.claude/skills/keel/ (real copy; re-run = reinstall)
                   also symlinks completion/_keel onto $fpath (oh-my-zsh auto-detected)
    engine/        the agnostic tool (code only, no domain words)
      cli.py         entry point (-h: render|lint|drift|status|todo|matrix|check|context|find|new; -hh adds view|index|watch)
      render.py      parse/union + 4 view primitives (table / join / entry / matrix)
      view.py        materialize the render to <dir>/<name>.view.md (live-preview artifact)
      lint.py        graph-internal gate
      drift.py       graph<->code drift gate (ripgrep, Rust + Python)
      status.py      divergence dashboard (exposes classify: impl/planned/drifted)
      todo.py        ranked worklist derived from the graph (fix > ready lanes > decide > blocked)
      matrix.py      derived coverage pivot: two edge kinds crossed through a table (gaps first-class)
      context.py     1-hop context of a node (--code-root: refs resolve inline) or a code coordinate (who pins it)
      index.py       derived repo-wide .toons/ roll-up + slug<->anchor invariant
      find.py        reverse lookup: a source path -> its anchoring container
      containers.py  shared .toons/ protocol core (slug math, discovery, reverse lookup)
      emit.py        shared agent-output layer (--toon / truncation / counts / errors / next)
      new.py         scaffold a fresh .toons/<slug>/ container (cold start)
      watch.py       poll .toons/, refresh previews + lint on change (human live loop)
    examples/      a self-contained .toons/ repo (root == examples/) that exercises the FULL
                   engine - the container protocol too, so watch/index/find/<slug> all fire
      .toons/src-auth/auth.graph.toon       agnosticism: a non-RNG vocabulary, all planned (no code)
      .toons/refs-fixtures/refs.graph.toon  ref-edge drift demo, anchored at refs/fixtures/
      refs/fixtures/{sample.py,degraded.rs} the code those ref edges resolve against
    completion/    _keel - zsh tab-completion (subcommands + this repo's .toons/ slugs)

# Run
Dev form (from this repo's root) is shown below; installed, swap `python engine/cli.py` for `keel`:

    python engine/cli.py new    <src-anchor>                # scaffold a fresh container (cold start)
    python engine/cli.py find   <src-file>                  # source -> its container (front door)
    python engine/cli.py context <node|file#sym> <target dir>  # 1-hop edit context (PICK); file#sym: who pins it
    python engine/cli.py check  <target dir> --root <code>  # lint + drift (the CHECK gate)
    python engine/cli.py status <target dir> --root <code>  # divergence dashboard
    python engine/cli.py todo   [goal] <target dir> --root <code>  # ranked worklist: what next
    python engine/cli.py matrix <target dir> [pivot "<a> x <b>"] --root <code>  # coverage pivot (no axes: candidates)
    python engine/cli.py render <target dir>                # human view
    python engine/cli.py watch  <target dir>                # live: poll .toons/, refresh + lint on change
    python engine/cli.py index                              # repo-wide .toons/ roll-up

`<target dir>` is a container dir, a file, or a bare `<slug>` (which resolves `.toons/<slug>/`
and defaults `--root`). `--root` is the CODE root for ref resolution (your crate/package),
separate from the graph dir. Query commands take `--toon` (structured body for an agent),
`--brief` (size-hinted truncation; output is FULL by default), and `-h`/`--help` (its own
reference); `new` / `view` / `index` / `watch` write files (a new container, a preview, the
roll-up, the watch status).

# Containers - where toons live in a large repo
Don't map the whole repo, only the IDEA LAYER that needs focused attention (a dense
module, a cross-cutting concept). Each concept is a container under a single `.toons/` dir
at the repo core; a container IS a graph dir, so the engine runs on it unchanged.

    <repo-root>/                            == --root
    ├── scripts/viz/lenses.py               <- the anchor (the idea layer)
    └── .toons/
        ├── _index.toon                     <- derived repo-wide roll-up (never hand-edited)
        └── scripts-viz-lenses/             <- one concept = one graph dir
            ├── lenses.graph.toon             slice: nodes/edges/invariants/decisions
            ├── lenses.views.toon             optional human views
            └── bodies/<node>.md              prose too big for a cell

    python <engine>/cli.py check scripts-viz-lenses    # <slug> resolves the dir + --root for you

Naming rule:

    slug = <PRIMARY anchor path relative to repo root>, '/' -> '-', source ext dropped
       scripts/viz/lenses.py  ->  scripts-viz-lenses    (file anchor)
       scripts/viz            ->  scripts-viz           (dir anchor)

Anchor granularity is a judgment call - a file, a dir, whatever the concept's home is. A
concept that SPANS DIRS picks ONE primary anchor for its slug and reaches the rest via
`ref` edges: the slug names the concept by its home, not its full footprint.

The slug and the slice's `refs: {logic: scripts/viz/lenses.py}` encode the SAME path, so
`slug == flatten(refs.logic)` is a checkable, unique-across-`.toons/` invariant. A collision
fails loud; the source extension is dropped, appended (`-py`/`-rs`) only when two anchors
would otherwise collide. That invariant makes `_index.toon` derivable (roll up each anchor's
planned/impl/drifted - it can't drift, nothing hand-writes it) and the front door a reverse
lookup (given a file you're about to edit, flatten + walk up to its container, or learn
there is no toon yet).

Three commands operationalize it (all in `containers.py`):

    index   walk .toons/*/, refresh the derived _index.toon board, and enforce the
            slug<->anchor invariant (a misnamed dir or an undisambiguable collision -> exit 1).
            --check validates without writing.
    find    reverse lookup: `find <source-path>` walks up to the anchoring container, or
            prints the candidate slugs + a bootstrap hint on a miss.
    <slug>  any command accepts a bare container slug in place of the dir path; it resolves
            .toons/<slug>/ and defaults --root to the repo root (walk up to .toons/'s parent).

Source-code edits are NOT watched (that would mean scanning the whole code root): graph<->code
drift is a pull-time gate. Run `check`/`drift` at RECONCILE, and use `find <source-path>` to map
a file you are about to edit to its container.

# Modeling rules
    node       = anything referenced elsewhere (else it is body text, not a node)
    column     = a literal ATTRIBUTE (card, severity) - never a reference
    state      = the `state` column: a node's commitment lane (explore/canon/dropped,
                 unset ≡ canon); orthogonal to the derived planned/implemented/drifted axis
    edge       = EVERY reference (bends, detects, calls, ref, ...) so lint catches a
                 typo'd target generically, with no domain code
    canonical  = intent + structure + decisions + invariants; logic/numbers are refs->code

# Proof it is algorithm-agnostic
`examples/.toons/src-auth/auth.graph.toon` models a web-auth spec (components / policies / an invariant) with
node and edge kinds the engine has never heard of, yet it renders and lints through the exact
same engine - zero engine changes. A spec may be partial: unresolved cross-slice refs are
listed, not failed - a property of the content, not the tool.
