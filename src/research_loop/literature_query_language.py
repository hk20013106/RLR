"""No downstream language policy.

User language is normalized once before canonical L0 is frozen. Literature
consumers use the canonical English state directly and do not re-validate or
translate language.
"""


def install(*_args, **_kwargs):
    return None
