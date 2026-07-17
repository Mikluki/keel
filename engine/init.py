#!/usr/bin/env python3
"""init: stand up (or re-attach) the sibling keel worktree - the split-repo bootstrap.

The graph lives on an orphan branch `keel`, materialized in a sibling <repo>-keel/ next to
the code tree - so a worker grepping the code repo never finds a toons/ on disk (the whole
point: isolation is structural, not a plea in an instruction file). The code the graph refs
against stays the main worktree; keel binds --code-root back to it automatically (containers.
code_root_for), so no long paths on every call. Idempotent, and it refuses a target inside the
code tree (a nested worktree would put the graph back on disk). Three paths, from what exists:

    CREATE   nothing yet          git worktree add --orphan -b keel <target>, scaffold toons/
    ATTACH   branch keel local    git worktree add <target> keel
    ATTACH   keel on the remote   git worktree add --track -b keel <target> origin/keel

    python init.py                         # -> ../<repo>-keel/  on branch keel
    python init.py ~/graphs/proj-keel      # explicit location (still must be outside the tree)
"""
import subprocess
import sys
from pathlib import Path

import emit
import containers

# derived artifacts, ignored on the keel branch exactly as they are in a co-located repo.
DERIVED_IGNORE = "*.view.md\n_index.toon\n_watch.status\n"


def git(root, *args, check=True):
    """Run `git -C root ...`; die loud on failure unless check=False (then return the result)."""
    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        emit.die('GIT', f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def main():
    args = emit.parse(sys.argv[1:], cmd='init', allow_root=False)

    # the code repo we bootstrap from = cwd's repo.
    top = git('.', 'rev-parse', '--show-toplevel', check=False)
    if top.returncode != 0:
        emit.die('NO_REPO', 'init must run inside the git repo whose code the graph will describe')
    main_root = Path(top.stdout.strip())

    # refuse if we are already standing in the keel worktree (run it from the code tree).
    cur = git('.', 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    if cur.stdout.strip() == containers.KEEL_BRANCH:
        emit.die('ON_KEEL', f"already inside the keel worktree (branch {containers.KEEL_BRANCH}) - "
                            "run init from the code tree", exit_code=3)

    # target worktree: sibling <repo>-keel/ by convention, or an explicit path.
    target = (Path(args.positional[0]) if args.positional
              else main_root.parent / f"{main_root.name}{containers.KEEL_WT_SUFFIX}").resolve()

    # it MUST be outside the code tree, else the graph lands back on disk (the whole point).
    if target == main_root.resolve() or main_root.resolve() in target.parents:
        emit.die('NESTED', f"target {target} is inside the code tree - the keel worktree must be a "
                           "sibling so the graph never shows up in the code repo")

    # already set up? idempotent if it is exactly ours, an error if it is elsewhere.
    for path, branch in containers.git_worktrees(main_root):
        if branch == containers.KEEL_BRANCH:
            if path.resolve() == target:
                _report('present', target, main_root, args.toon)
                return
            emit.die('EXISTS', f"a keel worktree already exists at {path} - use it, or "
                               "`git worktree remove` it first", exit_code=3)

    action = _create_or_attach(main_root, target)
    _report(action, target, main_root, args.toon)


def _create_or_attach(main_root, target):
    """CREATE a fresh orphan worktree, or ATTACH an existing local/remote keel branch."""
    branch = containers.KEEL_BRANCH
    if git(main_root, 'show-ref', '--verify', '--quiet', f'refs/heads/{branch}',
           check=False).returncode == 0:
        git(main_root, 'worktree', 'add', str(target), branch)                       # local
        return 'attached'
    if git(main_root, 'ls-remote', '--exit-code', '--heads', 'origin', branch,
           check=False).returncode == 0:
        git(main_root, 'worktree', 'add', '--track', '-b', branch,
            str(target), f'origin/{branch}')                                         # remote
        return 'attached'
    git(main_root, 'worktree', 'add', '--orphan', '-b', branch, str(target))         # fresh
    (target / containers.TOONS_DIR).mkdir(exist_ok=True)
    (target / '.gitignore').write_text(DERIVED_IGNORE)
    git(target, 'add', '-A')
    git(target, 'commit', '-m', 'keel: init graph worktree')   # borns the orphan branch
    return 'created'


def _report(action, target, main_root, toon):
    """One line of what happened + a next: hint into the worktree (guide-suppressed for agents)."""
    if toon:
        print(emit.toon({'worktree': str(target), 'branch': containers.KEEL_BRANCH,
                         'action': action, 'code_root': str(main_root)}, {}))
    else:
        print(f"{action} keel worktree {target}/  "
              f"(branch {containers.KEEL_BRANCH}, code-root {main_root})")
    emit.nxt(f"cd {target} && keel new <anchor>", toon=toon, guide=True)


if __name__ == '__main__':
    main()
