"""
Safe template rendering using {{variable}} placeholders.

Rules:
- No eval, no exec, no Jinja.
- Missing keys render as empty string — never raise.
- Values are coerced to str before substitution.
"""
import re

_PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")


def render_template(content: str, context: dict) -> str:
    def _sub(match):
        key = match.group(1).strip()
        value = context.get(key)
        return str(value) if value is not None else ""

    return _PLACEHOLDER.sub(_sub, content)
