## Philosophy

You are an AI assistant. Your role is to assist with development tasks while adhering to strict coding standards and practices. Here's how you should approach your work:

0. Base:
   - Scientific coding: aim for results, not perfection
   - Readability > complex APIs
   - No complex fallback logic unless specified
   - Every line of code is a liability—no CLI interfaces unless explicitly requested
   - Caching is mandatory for heavy computation
   - Note: too many features, info, or data is useless if it is just noise. Be respectful of attention span. More does not mean better.
   - Use consistent explicit arg names across functions especially when they share the same physical meaning.

1. Critical Coding Rules:
   - Prioritize simple, clean, and maintainable solutions over clever or complex ones.
   - Make the smallest reasonable changes to achieve the desired outcome.
   - Never make unrelated code changes; document issues for later instead.
   - Preserve code comments unless you can prove they are actively false.
   - Start all code files with a module-level header comment block explaining the file's purpose, prefixed with "ABOUTME: ". Make file features, io operations, and input/output paths transparent.
   - Avoid temporal context in comments; make them evergreen.

2. Avoiding entropy
   - Don't take shortcuts that create future burden. Note tech debt inline as a comment instead of silently hacking around it.

## Documentation Discipline

Never create bloat files. Every markdown file is a maintenance burden.

**Documentation Hierarchy** (only these files at root level):

- `README.md` — Overview + quick start only

**Before creating any .md file, ask:**

1. Does this content already exist elsewhere?
2. Will someone actually read this, or is it info noise?
3. Should this live in code comments instead?
4. Could this be a 5-line section in an existing file instead of a new file?

**Don't create at root:**

- Detailed pipeline docs (put in code ABOUTME comments + README)
- Per-script documentation (use script-level ABOUTME comments)
`ABOUTME:` is a **grep handle** — it appears on the **first line only**. Continuation lines are plain comments with no tag. Never repeat `ABOUTME:` on line 2+; it defeats `grep ABOUTME` as a file index.

**Single-task constraint:**
If a task produces multiple .md files at root level, it's a sign the task was too broad or the files should be consolidated.


## Environment

Python is strictly managed through uv virtual environments. Use local uv venv.

## Conventions

- Function args: explicit names, `Path` objects only (no raw strings), dataclass if config > 3 params
- Two output streams, never mixed. **stdout = payload** (a command's data / return
  value): use `print()` (or a shared emit) and keep it pure so it pipes and stays
  token-lean. **stderr = diagnostics** (progress, warnings, errors): use `logging`
  (shadow via level). Never route payload through logging - its level/timestamp prefixes
  are noise and pollute stdout. The logging template below is for the diagnostics stream.
- Logging template (diagnostics -> stderr/file):
  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
      datefmt="%H:%M:%S",
      handlers=[
          logging.FileHandler(output_dir / f"{Path(__file__).stem}.log"),
          logging.StreamHandler(),
      ],
  )
  LOGGER = logging.getLogger(__name__)
  ```
- Code: black (88 char), section separators (see below), ABOUTME comments on all scripts

## Python Code Style — Section Separators

```python
# ============================================================================
# CONFIG
# ============================================================================

# ============================================================================
# LOGGING
# ============================================================================

# ============================================================================
# FUNCTIONS
# ============================================================================

# ============================================================================
# CLASSES
# ============================================================================
```

