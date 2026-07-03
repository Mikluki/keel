"""Python fixture for ref-resolve's Python definition patterns (examples/refs).

Only exists so the demo can resolve a Python symbol without reaching into engine/.
`keyed_uniform` is defined here AND in degraded.rs so a bare-symbol search is AMBIGUOUS.
"""


def keyed_uniform(seed, step):
    _ = (seed, step)
    return 0.0


class DefectHooks:
    bias = 0.0
