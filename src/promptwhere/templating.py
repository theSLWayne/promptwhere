"""Template variable detection and rendering, using Python ``{variable}`` syntax."""

from __future__ import annotations

import re
import string
from typing import Any

_ROOT_RE = re.compile(r"[^.\[]*")


def find_variables(template: str) -> list[str]:
    """Return the distinct variable names in ``template``, in order of first use.

    ``{user.name}`` and ``{items[0]}`` count as the variable ``user`` / ``items``.
    Literal braces are written ``{{`` and ``}}``.

    Raises:
        ValueError: If the template has unbalanced braces or a field that is not a
            plain variable name (such as ``{}``, ``{0}`` or JSON like ``{"a": 1}``).
    """
    names: list[str] = []
    _collect(template, names)
    return names


def _collect(template: str, names: list[str]) -> None:
    try:
        fields = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ValueError(
            f"Invalid template: {exc}. Write a literal brace as '{{{{' or '}}}}'."
        ) from None
    for _, field_name, format_spec, _ in fields:
        if field_name is None:
            continue
        match = _ROOT_RE.match(field_name)
        root = match.group() if match else ""
        if not root.isidentifier():
            raise ValueError(
                f"Invalid template field {{{field_name}}}: use named variables like "
                "{name}. If you meant a literal brace, write '{{' or '}}'."
            )
        if root not in names:
            names.append(root)
        if format_spec:  # nested fields, e.g. {value:{width}}
            _collect(format_spec, names)


def render_template(template: str, variables: dict[str, Any]) -> tuple[str, list[str]]:
    """Fill ``template``. Returns ``(text, missing)``; ``text`` is empty if any are missing."""
    missing = [name for name in find_variables(template) if name not in variables]
    if missing:
        return "", missing
    return template.format(**variables), []
