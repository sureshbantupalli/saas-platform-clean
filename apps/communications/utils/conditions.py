"""
Simple JSON condition evaluator.

Condition format (all top-level keys must pass — implicit AND):
    {
        "amount":         {">": 1000, "<=": 5000},
        "payment_method": {"==": "online"},
        "is_renewal":     {"==": true}
    }

Supported operators: == != > < >= <=
Missing fields or type errors → condition fails (returns False).
Unknown operators are skipped (not an error).
"""

_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">":  lambda a, b: float(a) > float(b),
    "<":  lambda a, b: float(a) < float(b),
    ">=": lambda a, b: float(a) >= float(b),
    "<=": lambda a, b: float(a) <= float(b),
}


def evaluate_conditions(conditions: dict, payload: dict) -> bool:
    """Return True if all conditions pass (or conditions is empty)."""
    if not conditions:
        return True

    for field, checks in conditions.items():
        actual = payload.get(field)
        if actual is None:
            return False

        if not isinstance(checks, dict):
            # Shorthand equality: {"field": "value"}
            if actual != checks:
                return False
            continue

        for op, expected in checks.items():
            fn = _OPS.get(op)
            if fn is None:
                continue
            try:
                if not fn(actual, expected):
                    return False
            except (TypeError, ValueError):
                return False

    return True
