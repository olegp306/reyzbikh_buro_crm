"""Prompt-template rendering.

Templates live as ``.j2`` files alongside this module. ``render(name, **vars)``
loads the template from the package directory and returns the rendered text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **variables: Any) -> str:
    """Render the named ``.j2`` template with the supplied variables.

    Raises a Jinja UndefinedError if the template references a variable
    that wasn't supplied (StrictUndefined). Use ``render('extract_lead',
    raw_text='...')``.
    """
    template = _env.get_template(template_name + ".j2")
    return template.render(**variables)
