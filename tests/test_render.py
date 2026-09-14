"""The write side of the frontmatter format: what is rendered must parse back unchanged."""

from pathlib import Path

import pytest
import yaml

from kb import schema


@pytest.mark.parametrize(
    "value",
    [
        "A plain title",
        "Note: this one has a colon",
        "A title with a | pipe",
        "Ends with a colon:",
        "2026-09-14",
        "true",
        "- starts with a dash",
        "#starts with a hash",
        "[[looks/like|a wikilink]]",
        'has "double quotes" inside',
        "has a backslash \\ inside",
    ],
)
def test_a_rendered_scalar_parses_back_to_itself(value: str) -> None:
    rendered = schema.render_frontmatter({"summary": value})
    assert yaml.safe_load(rendered) == {"summary": value}


def test_a_rendered_list_parses_back_to_itself() -> None:
    items = ["[[runbooks/a|A Title]]", "plain", "with, a comma", "with: a colon"]
    rendered = schema.render_frontmatter({"related": items})
    assert yaml.safe_load(rendered) == {"related": items}


def test_fields_come_out_in_the_order_schema_documents() -> None:
    rendered = schema.render_frontmatter(
        {"summary": "s", "title": "t", "note": "n", "type": "guide", "status": "stable"}
    )
    assert [line.split(":")[0] for line in rendered.splitlines()] == ["title", "type", "status", "summary", "note"]


def test_an_unknown_field_is_kept_and_sorted_after_the_known_ones() -> None:
    rendered = schema.render_frontmatter({"title": "t", "zeta": "z", "alpha": "a"})
    assert [line.split(":")[0] for line in rendered.splitlines()] == ["title", "alpha", "zeta"]


def test_an_empty_value_is_dropped_but_an_empty_list_is_kept() -> None:
    # `related: []` says "checked, nothing related"; a missing field says "never considered".
    rendered = schema.render_frontmatter({"title": "t", "summary": "", "note": None, "related": []})
    assert yaml.safe_load(rendered) == {"title": "t", "related": []}


def test_a_rendered_article_parses_as_an_article(tmp_path: Path) -> None:
    text = schema.render_article(
        {"title": "Note: a title", "type": "guide", "summary": "One | two", "related": ["[[a/b|B]]"]},
        "# Heading\n\nBody text.\n",
    )
    path = tmp_path / "guides" / "a.md"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    parsed = schema.parse_article(path, tmp_path)
    assert parsed.title == "Note: a title"
    assert parsed.summary == "One | two"
    assert parsed.list_field("related") == ["[[a/b|B]]"]
    assert "Body text." in parsed.body


def test_slugify_produces_a_filename_safe_slug() -> None:
    assert schema.slugify("Diagnosing a Slow / Stuck JVM Pod!") == "diagnosing-a-slow-stuck-jvm-pod"
    assert schema.slugify("--already-a-slug--") == "already-a-slug"


def test_a_date_field_that_arrived_as_a_string_renders_bare() -> None:
    # Re-rendering an article read back from disk must not re-quote its dates, or every
    # touch leaves one date quoted and its neighbour not.
    rendered = schema.render_frontmatter({"created": "2026-07-26", "last_updated": "2026-09-14"})
    assert rendered == "created: 2026-07-26\nlast_updated: 2026-09-14"
    assert yaml.safe_load(rendered)["created"].isoformat() == "2026-07-26"


def test_a_date_field_that_is_not_a_date_is_left_alone() -> None:
    rendered = schema.render_frontmatter({"created": "whenever"})
    assert yaml.safe_load(rendered) == {"created": "whenever"}


def test_rendering_an_article_twice_is_stable(tmp_path: Path) -> None:
    first = schema.render_article({"title": "T", "created": "2026-07-26", "summary": "S"}, "Body.\n")
    front, body, _ = schema.split_frontmatter(first)
    second = schema.render_article(yaml.safe_load(front), body)
    assert first == second
