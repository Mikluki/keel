# keel TOON graph - grammar reference

<!-- ABOUTME: the full TOON grammar a keel slice is written in - node tables, edges,
     views, rules, and the reserved columns the engine understands. Copy these shapes when
     hand-authoring a `*.graph.toon` / `*.views.toon`. Recreated stub - verify against the
     engine (engine/render.py parse_toon + lint.py) and the live examples. -->

The engine (`render.py parse_toon`) reads a deliberately tiny subset of TOON. It knows only
four structural things - **node tables**, `edges`, `views`, `rules` - and NO domain
vocabulary: which node/edge KINDS exist and which VIEWS to draw are all declared as data
here. A complete slice to copy is at the end of this file; the same spec also lives as a
standalone file at `examples/auth.graph.toon` in the repo.

## Contents
- Line grammar
- Scalars (file metadata)
- Node tables (everything not named edges/views/rules)
- `edges` - every relationship (reserved table)
- `views` - presentation (reserved table; usually in a `*.views.toon`)
- `rules` - declarative gates (reserved table)
- File conventions
- A complete slice to copy

## Line grammar

A slice file is just two line shapes:

    key: value                     # a scalar (file-level metadata)
    name[N]{col1,col2,...}:        # a table header: N rows, named columns
      v1,v2,...                    # CSV rows, one per line, until a blank line or the next header

Rows are parsed with a CSV reader, so quote any value containing a comma:
`"100 req/min per IP, enforced at the gateway"`. A table's rows end at a blank line or the
next table header; the declared `[N]` is a validated CHECKSUM, not load-bearing - a
mismatch is a hard error naming both numbers. So a surgical row edit is safe: insert or
delete the row in place, and if you forget the count the engine tells you the fix
verbatim. Nothing else is significant - no nesting, no types.

## Scalars (file metadata)

    slice: auth-demo                                  # the slice's short id (shown in lint/render)
    owns: a tiny non-RNG spec proving the engine is vocabulary-agnostic # what this slice covers
    refs: {logic: src/auth/, numbers: results/}       # freeform pointers to code/results roots

`slice` labels the slice, and `refs.logic` is the PRIMARY code anchor - the engine reads it
(`render.py`) and it drives the container slug, the `detail` view's `Logic ->` line, and
`ref`/`status` resolution. `owns` and any non-`logic` `refs` keys (e.g. `numbers:`) are
documentation.

## Node tables (everything not named edges/views/rules)

Any table whose name is not a reserved word is a **node table**. Each row is a node; its
`id` column is the node's identity (referenced by edges, touches, views, rules). All other
columns are **literal attributes** - free text the engine never interprets:

    components[3]{id,layer,card}:
      gateway,edge,"terminates TLS, routes requests, rate-limits"
      authsvc,core,"issues and verifies bearer tokens"
      userdb,data,"stores argon2 credential hashes"

Reserved columns understood on node/constraint rows:

- **`id`** - the node identity. Must be unique across all node tables in the union (lint fails on dupes).
- **`state`** - commitment lane: `canon` | `explore` | `dropped` (absent = `canon`; an unknown
  value is flagged by lint and treated as canon). What each lane means for `check`/`render` is
  covered in SKILL.md's "New ideas" section, not repeated here.
- **`touches`** - a comma-separated list of node ids this row relates to. Used on
  constraint tables (invariants, decisions) so the `detail` view can gather every rule that
  touches a node, and lint can check the targets resolve. Example:
  `mfa-required,"authsvc,mfa","admin scopes always require the second factor"`.

Constraint tables are just node tables by convention - nothing special to the engine:

    invariants[1]{id,touches,statement}:
      no-plaintext,"userdb,authsvc","credentials are argon2-hashed; authsvc never logs them"

    decisions[1]{id,touches,chose,rejected,why}:
      D-ratelimit,ratelimit,"100 req/min per IP",unlimited,"unlimited invites credential stuffing"

## `edges` - every relationship (reserved table)

    edges[N]{kind,from,to}:
      calls,gateway,authsvc               # a domain edge: kind is free vocabulary
      reads,authsvc,userdb
      ref,authsvc,src/auth/service.py#AuthService   # special: a code reference

- `kind` is free domain vocabulary (bends, detects, calls, reads, enforces, pins, reuses, ...).
- `from`/`to` normally name a node `id`, but may also be a table NAME (a category). An
  endpoint that resolves to neither is SURFACED by lint as an "unresolved cross-slice ref" -
  listed, not a hard error (it may live in a slice you did not load together). A missing CODE
  target on a `ref` edge is the separate, hard `drift`/`check` gate.
- **`ref` edges are special**: `to` is a CODE coordinate, not a node id, and is checked by
  `drift.py` (ripgrep), not node resolution. Three target forms:
  - `file.py#symbol` / `file.rs#Struct` - a symbol in a specific file. A symbol is any
    definition, module-level constants included: `file.py#BOOT_REPS` matches
    `BOOT_REPS = ...` / `BOOT_REPS: int = ...`, `file.rs#MAX_LAG` matches `const`/`static`.
  - `path/to/file.rs` - a whole file
  - `bare_symbol` - searched across `--code-root` (ambiguous if it hits multiple files)

  So a CHOSEN number (threshold, window, pre-registered constant) never appears in the
  graph: the card states the decision, the `ref` names the constant, the value lives in
  code. The value can churn with zero graph diff; a rename fails `check`.
  `keel context <file#CONST>` answers the reverse - which nodes pin that code.

## `views` - presentation (reserved table; usually in a `*.views.toon`)

    views[N]{kind,title,table,arg,extra}:
      table,Components,components,"id,layer,card",          # arg = columns to show
      join,Enforced policies,components,enforces,card         # arg = edge kind, extra = other-endpoint column
      detail,Component detail,components,,                    # arg/extra empty

Three view primitives (the only ones the renderer knows):

- **`table`** - list a node table. `arg` = comma-separated columns to print.
- **`join`** - per node in `table`, follow every edge of kind `arg` and print the other
  endpoint plus its `extra` column.
- **`detail`** - per node in `table`, print its attributes, its prose `bodies/<id>.md`, every
  row that `touches` it, and its `ref -> code` target.

## `rules` - declarative gates (reserved table)

    rules[N]{kind,a,b}:
      needs-edge,components,calls     # every canon node in `components` must be touched by a `calls` edge
      undirected,overlaps,            # `overlaps` edges are symmetric associations, not dependencies

- **`needs-edge`**: every `canon` node in table `a` must be an endpoint of at least one edge
  of kind `b`; lint fails otherwise. (explore/dropped nodes are exempt.)
- **`undirected`**: edge kind `a` is a symmetric association, not a dependency (`b` stays
  empty) - exempts it from the gate that fails a `canon` node whose edge points at an
  `explore`/`dropped` one. Why this exists and when to reach for it instead of flipping an
  edge: SKILL.md's "Rules of the model". (Join views already render both directions, so
  nothing else changes.)
- Any other rule kind is a lint ERROR - a typo'd rule must fail loud, not silently gate nothing.

## File conventions

- `*.graph.toon` - a slice's nodes + edges (+ invariants/decisions/rules).
- `*.views.toon` - presentation only; renders against one or more graph slices (`views`/`rules`
  can live in either - they union across all loaded slices).
- `bodies/<id>.md` - a node's prose drill-down, surfaced by `context`, the `detail` view (clipped),
  and the render's trailing appendix (full text, one `## <id>` per body, grouped under
  `# Canon`/`# Explore`/`# Dropped`).
- `*.results.toon` - an OPT-IN measurement sidecar for an EMPIRICAL graph only (see SKILL.md
  "Measurements"; ask before introducing one). A `result{id,touches,run,finding,data}` table
  keyed by the node id it measures - `touches` wires it to that node (lint-checked), and a
  `ref` edge on the result points at the data artifact under `refs.numbers` for existence-drift.
  Auto-unioned from a graph dir like any slice (so `touches`/`ref` resolve), but kept a separate
  file so its high-churn diffs never touch the low-diff graph. Not created by default.
- Multiple slices passed together are unioned before lint/render, so refs resolve across them.

## A complete slice to copy

A full, tiny, domain-agnostic example (non-RNG, so nothing here is engine vocabulary):

    slice: auth-demo
    owns: a tiny non-RNG spec - proves the engine is vocabulary-agnostic
    refs: {logic: src/auth/}

    components[3]{id,layer,card}:
      gateway,edge,"terminates TLS, routes requests, rate-limits"
      authsvc,core,"issues and verifies bearer tokens"
      userdb,data,"stores argon2 credential hashes"

    policies[2]{id,card}:
      ratelimit,"100 req/min per IP, enforced at the gateway"
      mfa,"second factor required for admin scopes"

    invariants[1]{id,touches,statement}:
      no-plaintext,"userdb,authsvc","credentials are argon2-hashed; authsvc never logs them"

    edges[4]{kind,from,to}:
      calls,gateway,authsvc
      reads,authsvc,userdb
      enforces,gateway,ratelimit
      enforces,authsvc,mfa

    views[3]{kind,title,table,arg,extra}:
      table,Components,components,"id,layer,card",
      join,Enforced policies,components,enforces,card
      detail,Component detail,components,,
