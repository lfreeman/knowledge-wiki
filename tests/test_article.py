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


def test_a_bumped_date_is_written_unquoted(article: ArticleWriter, vault: Path) -> None:
    # A quoted date beside an unquoted one in the same block is noise in every later diff.
    article("systems/a", created="2026-09-13", last_updated="2020-01-01")
    runner.invoke(app, ["article", "touch", "systems/a", "--on", "2026-09-14", "--no-dry-run"])
    front, _, _ = schema.split_frontmatter((vault / "systems" / "a.md").read_text())
    assert "last_updated: 2026-09-14" in front
    assert '"' not in front.split("last_updated:")[1].splitlines()[0]


def test_a_new_article_writes_both_dates_unquoted(vault: Path) -> None:
    runner.invoke(app, [*BASE, "--created", "2026-09-13", "--no-dry-run"])
    front, _, _ = schema.split_frontmatter((vault / "runbooks" / "a-slug.md").read_text())
    assert "created: 2026-09-13" in front
    assert f"last_updated: {date.today().isoformat()}" in front


def test_touch_rejects_a_date_it_cannot_parse(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01")
    result = runner.invoke(app, ["article", "touch", "systems/a", "--on", "last tuesday", "--no-dry-run"])
    assert result.exit_code == 1
    assert schema.parse_article(vault / "systems" / "a.md", vault).date_field("last_updated") == date(2020, 1, 1)


def test_new_rejects_a_created_date_it_cannot_parse(vault: Path) -> None:
    result = runner.invoke(app, [*BASE, "--created", "whenever", "--no-dry-run"])
    assert result.exit_code == 1
    assert not (vault / "runbooks" / "a-slug.md").exists()


def test_link_writes_the_relation_into_both_articles(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", title="Article A")
    article("runbooks/b", title="Article B")
    assert runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"]).exit_code == 0
    assert schema.parse_article(vault / "systems" / "a.md", vault).list_field("related") == [
        "[[runbooks/b|Article B]]"
    ]
    assert schema.parse_article(vault / "runbooks" / "b.md", vault).list_field("related") == [
        "[[systems/a|Article A]]"
    ]


def test_link_takes_each_alias_from_the_other_articles_own_title(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", title="Collaborative Insights — How It Works")
    article("runbooks/b", title="Article B")
    runner.invoke(app, ["article", "link", "runbooks/b", "systems/a", "--no-dry-run"])
    (link,) = schema.parse_article(vault / "runbooks" / "b.md", vault).list_field("related")
    assert link == "[[systems/a|Collaborative Insights — How It Works]]"


def test_link_clears_the_orphan_warning(article: ArticleWriter, vault: Path) -> None:
    from kb.commands.lint import check

    article("systems/a")
    article("runbooks/b")
    assert {f.path for f in check(vault) if f.rule == "orphan"} == {"systems/a.md", "runbooks/b.md"}
    runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"])
    assert [f for f in check(vault) if f.rule == "orphan"] == []


def test_link_is_idempotent(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    article("runbooks/b")
    runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"])
    result = runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"])
    assert "already present" in result.output
    assert len(schema.parse_article(vault / "systems" / "a.md", vault).list_field("related")) == 1


def test_link_keeps_an_existing_relation(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", related=["[[guides/c|Article C]]"])
    article("runbooks/b", title="Article B")
    runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).list_field("related") == [
        "[[guides/c|Article C]]",
        "[[runbooks/b|Article B]]",
    ]


def test_link_bumps_last_updated_on_what_it_edited(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01")
    article("runbooks/b", last_updated="2020-01-01")
    runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).date_field("last_updated") == date.today()


def test_link_one_way_touches_only_the_first(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    article("runbooks/b")
    runner.invoke(app, ["article", "link", "systems/a", "runbooks/b", "--one-way", "--no-dry-run"])
    assert schema.parse_article(vault / "runbooks" / "b.md", vault).list_field("related") == []


def test_link_is_a_preview_by_default(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    article("runbooks/b")
    result = runner.invoke(app, ["article", "link", "systems/a", "runbooks/b"])
    assert "would add" in result.output
    assert schema.parse_article(vault / "systems" / "a.md", vault).list_field("related") == []


def test_link_fails_when_either_article_is_missing(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    assert runner.invoke(app, ["article", "link", "systems/a", "runbooks/nope", "--no-dry-run"]).exit_code == 1
