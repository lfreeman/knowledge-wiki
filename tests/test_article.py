"""`kb article new` and `kb article touch`."""

import json
from datetime import date
from pathlib import Path

from conftest import ArticleWriter
from typer.testing import CliRunner

from kb import schema
from kb.cli import app

runner = CliRunner()

BASE = ["article", "new", "runbooks/a-slug", "--title", "A Title", "--summary", "What it establishes."]


def test_new_is_a_preview_by_default(vault: Path) -> None:
    result = runner.invoke(app, BASE)
    assert result.exit_code == 0
    assert not (vault / "runbooks" / "a-slug.md").exists()
    assert "Would write" in result.output


def test_new_writes_an_article_that_parses_and_lints_clean(vault: Path) -> None:
    result = runner.invoke(app, [*BASE, "--repo", "some-service", "--system", "SomeThing", "--no-dry-run"])
    assert result.exit_code == 0
    parsed = schema.parse_article(vault / "runbooks" / "a-slug.md", vault)
    assert parsed.title == "A Title"
    assert parsed.type == "runbook"
    assert parsed.status == "stable"
    assert parsed.summary == "What it establishes."
    assert parsed.list_field("repos") == ["some-service"]
    assert parsed.date_field("last_updated") == date.today()


def test_new_infers_the_type_from_the_directory(vault: Path) -> None:
    runner.invoke(app, ["article", "new", "systems/a", "--title", "T", "--summary", "S", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).type == "system"


def test_new_takes_the_body_from_a_file_verbatim(vault: Path, tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text("# A Title\n\nProse with `backticks`, an apostrophe's quote and a $VAR.\n", encoding="utf-8")
    runner.invoke(app, [*BASE, "--body-file", str(body), "--no-dry-run"])
    parsed = schema.parse_article(vault / "runbooks" / "a-slug.md", vault)
    assert "apostrophe's quote and a $VAR" in parsed.body


def test_new_quotes_a_summary_containing_a_colon(vault: Path) -> None:
    runner.invoke(
        app,
        ["article", "new", "guides/a", "--title", "T", "--summary", "Note: it has a colon.", "--no-dry-run"],
    )
    assert schema.parse_article(vault / "guides" / "a.md", vault).summary == "Note: it has a colon."


def test_new_refuses_to_overwrite_an_existing_article(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/a-slug", body="the original body")
    result = runner.invoke(app, [*BASE, "--no-dry-run"])
    assert result.exit_code == 1
    assert "the original body" in (vault / "runbooks" / "a-slug.md").read_text()


def test_new_rejects_a_slug_with_no_directory(vault: Path) -> None:
    result = runner.invoke(app, ["article", "new", "a-slug", "--title", "T", "--summary", "S", "--no-dry-run"])
    assert result.exit_code == 1


def test_new_json_carries_the_article_it_would_write(vault: Path) -> None:
    payload = json.loads(runner.invoke(app, [*BASE, "--json"]).output)
    assert payload["dry_run"] is True
    assert payload["article"].startswith("---\ntitle: A Title")


def test_touch_bumps_last_updated_and_keeps_the_body(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", body="# A\n\nThe body must survive.\n", last_updated="2020-01-01")
    assert runner.invoke(app, ["article", "touch", "systems/a", "--no-dry-run"]).exit_code == 0
    parsed = schema.parse_article(vault / "systems" / "a.md", vault)
    assert parsed.date_field("last_updated") == date.today()
    assert "The body must survive." in parsed.body


def test_touch_keeps_every_other_field(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01", repos=["some-service"], related=["[[runbooks/b|B]]"])
    runner.invoke(app, ["article", "touch", "systems/a", "--no-dry-run"])
    parsed = schema.parse_article(vault / "systems" / "a.md", vault)
    assert parsed.list_field("repos") == ["some-service"]
    assert parsed.list_field("related") == ["[[runbooks/b|B]]"]


def test_touch_is_a_preview_by_default(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01")
    result = runner.invoke(app, ["article", "touch", "systems/a"])
    assert "Would bump" in result.output
    assert schema.parse_article(vault / "systems" / "a.md", vault).date_field("last_updated") == date(2020, 1, 1)


def test_touch_takes_an_explicit_date(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    runner.invoke(app, ["article", "touch", "systems/a", "--on", "2026-03-04", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).date_field("last_updated") == date(2026, 3, 4)


def test_touch_takes_several_slugs(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01")
    article("runbooks/b", last_updated="2020-01-01")
    payload = json.loads(runner.invoke(app, ["article", "touch", "systems/a", "runbooks/b", "--json"]).output)
    assert [entry["slug"] for entry in payload["changed"]] == ["systems/a", "runbooks/b"]


def test_touch_fails_on_a_missing_article(vault: Path) -> None:
    assert runner.invoke(app, ["article", "touch", "systems/nope", "--no-dry-run"]).exit_code == 1
