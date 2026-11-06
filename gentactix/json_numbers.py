"""Shared JSON transport projection; never round or repair physical state."""
import math


def canonical_numbers(value):
    """Match JS JSON round trips: 4.0 and 4 denote the same finite value.

    Fractions, booleans and nonfinite values are never rounded or repaired;
    ordinary domain validators still decide whether those inputs are legal.
    Callers apply this projection to transport inputs, never a live world.
    """
    if isinstance(value, dict):
        return {k: canonical_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical_numbers(v) for v in value]
    return int(value) if type(value) is float and math.isfinite(value) and value.is_integer() else value
