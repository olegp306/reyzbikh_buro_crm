from __future__ import annotations

import pytest

from crm.prompts import render


def test_render_extract_lead_template_contains_raw_text() -> None:
    out = render("extract_lead", raw_text="Иван дом 200 м2")
    assert "Иван дом 200 м2" in out
    assert '"full_name"' in out


def test_render_generate_proposal_template_contains_summary_and_json() -> None:
    out = render(
        "generate_proposal",
        lead_summary="apartment renovation",
        extracted_json='{"area_m2": 60}',
    )
    assert "apartment renovation" in out
    assert '"area_m2"' in out


def test_render_strict_undefined() -> None:
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        render("extract_lead")  # missing raw_text
