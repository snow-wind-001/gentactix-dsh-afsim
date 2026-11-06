"""Finite decimal literals for WSF Script, without changing model precision."""
from decimal import Decimal
import math


def number(value, *, precision=None):
    # WSF rejects tokens such as 3e-12. Expanding the already rounded decimal
    # preserves accumulated balances; rounding small values to zero does not.
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('AFSIM requires a finite numeric literal')
    text = str(value) if precision is None else format(value, f'.{precision}g')
    return format(Decimal(text), 'f')
