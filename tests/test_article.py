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


def test_a_dated_slug_sets_created_without_any_flag(vault: Path) -> None:
    # Incidents are named YYYY-MM-DD-slug, which by definition means backdating. Nobody
    # should have to discover a flag to get the date right on exactly those articles.
    runner.invoke(
        app,
        ["article", "new", "incidents/2026-06-25-a-thing", "--title", "T", "--summary", "S", "--no-dry-run"],
    )
    parsed = schema.parse_article(vault / "incidents" / "2026-06-25-a-thing.md", vault)
    assert parsed.date_field("created") == date(2026, 6, 25)
    assert parsed.date_field("last_updated") == date.today()


def test_an_explicit_created_wins_over_the_slug_but_warns(vault: Path) -> None:
    result = runner.invoke(
        app,
        [
            "article", "new", "incidents/2026-06-25-a-thing", "--title", "T", "--summary", "S",
            "--created", "2026-07-01", "--no-dry-run",
        ],
    )
    assert "warning" in result.output.lower()
    parsed = schema.parse_article(vault / "incidents" / "2026-06-25-a-thing.md", vault)
    assert parsed.date_field("created") == date(2026, 7, 1)


def test_an_agreeing_created_does_not_warn(vault: Path) -> None:
    result = runner.invoke(
        app,
        [
            "article", "new", "incidents/2026-06-25-a-thing", "--title", "T", "--summary", "S",
            "--created", "2026-06-25", "--no-dry-run",
        ],
    )
    assert "warning" not in result.output.lower()


def test_an_undated_slug_still_defaults_to_today(vault: Path) -> None:
    runner.invoke(app, [*BASE, "--no-dry-run"])
    assert schema.parse_article(vault / "runbooks" / "a-slug.md", vault).date_field("created") == date.today()


# --- the write-time overlap check, backlinks, and tagging ---


def test_new_warns_about_articles_sharing_a_system(article: ArticleWriter, vault: Path) -> None:
    # A search run minutes earlier cannot see what landed since; this can.
    article("systems/existing", title="Existing", systems=["Athena", "geohash"])
    result = runner.invoke(
        app,
        ["article", "new", "research/fresh", "--title", "T", "--summary", "S", "--system", "Athena", "--no-dry-run"],
    )
    assert result.exit_code == 0
    assert "systems/existing" in result.output
    assert "Athena" in result.output


def test_new_reports_overlap_on_repos_and_tickets_too(article: ArticleWriter, vault: Path) -> None:
    article("systems/existing", title="Existing", repos=["some-service"], tickets=["PROJ-1"])
    payload = json.loads(
        runner.invoke(
            app,
            ["article", "new", "research/fresh", "--title", "T", "--summary", "S",
             "--repo", "some-service", "--ticket", "PROJ-1", "--json"],
        ).output
    )
    (overlap,) = payload["overlaps"]
    assert overlap["slug"] == "systems/existing"
    assert set(overlap["shared"]) == {"some-service", "PROJ-1"}


def test_new_says_nothing_when_there_is_no_overlap(article: ArticleWriter, vault: Path) -> None:
    article("systems/existing", title="Existing", systems=["Athena"])
    payload = json.loads(
        runner.invoke(
            app,
            ["article", "new", "research/fresh", "--title", "T", "--summary", "S", "--system", "Kafka", "--json"],
        ).output
    )
    assert payload["overlaps"] == []


def test_new_writes_the_reverse_of_every_related_link(article: ArticleWriter, vault: Path) -> None:
    article("systems/other", title="Other Article")
    runner.invoke(
        app,
        ["article", "new", "research/fresh", "--title", "Fresh", "--summary", "S",
         "--related", "[[systems/other|Other Article]]", "--no-dry-run"],
    )
    assert schema.parse_article(vault / "systems" / "other.md", vault).list_field("related") == [
        "[[research/fresh|Fresh]]"
    ]


def test_new_skips_a_related_target_that_does_not_exist(vault: Path) -> None:
    result = runner.invoke(
        app,
        ["article", "new", "research/fresh", "--title", "Fresh", "--summary", "S",
         "--related", "[[systems/nope|Nope]]", "--no-dry-run"],
    )
    assert result.exit_code == 0
    assert schema.parse_article(vault / "research" / "fresh.md", vault).list_field("related") == [
        "[[systems/nope|Nope]]"
    ]


def test_link_after_related_is_safe(article: ArticleWriter, vault: Path) -> None:
    # Running link afterwards must not double the entry.
    article("systems/other", title="Other Article")
    runner.invoke(
        app,
        ["article", "new", "research/fresh", "--title", "Fresh", "--summary", "S",
         "--related", "[[systems/other|Other Article]]", "--no-dry-run"],
    )
    runner.invoke(app, ["article", "link", "research/fresh", "systems/other", "--no-dry-run"])
    assert len(schema.parse_article(vault / "systems" / "other.md", vault).list_field("related")) == 1


def test_new_previews_a_related_link_without_reading_the_article_it_has_not_written(
    article: ArticleWriter, vault: Path
) -> None:
    # The skill's flow is preview, then write. Taking the alias off disk made the preview
    # read a file the preview had deliberately not created.
    article("systems/other", title="Other Article")
    result = runner.invoke(
        app,
        ["article", "new", "research/fresh", "--title", "Fresh", "--summary", "S",
         "--related", "[[systems/other|Other Article]]"],
    )
    assert result.exit_code == 0
    assert not (vault / "research" / "fresh.md").exists()
    assert "systems/other" in result.output
    assert schema.parse_article(vault / "systems" / "other.md", vault).list_field("related") == []


def test_touch_says_so_when_the_date_is_already_current(article: ArticleWriter) -> None:
    article("systems/a", last_updated=date.today().isoformat())
    result = runner.invoke(app, ["article", "touch", "systems/a", "--no-dry-run"])
    assert "already current" in result.output
    assert "->" not in result.output


def test_tag_adds_values_to_an_existing_article(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", systems=["Athena"])
    runner.invoke(app, ["article", "tag", "systems/a", "--system", "geohash", "--repo", "some-service",
                        "--no-dry-run"])
    parsed = schema.parse_article(vault / "systems" / "a.md", vault)
    assert parsed.list_field("systems") == ["Athena", "geohash"]
    assert parsed.list_field("repos") == ["some-service"]


def test_tag_does_not_duplicate_a_value(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", systems=["Athena"])
    runner.invoke(app, ["article", "tag", "systems/a", "--system", "athena", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).list_field("systems") == ["Athena"]


def test_tag_can_remove(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", systems=["Athena", "geohash"])
    runner.invoke(app, ["article", "tag", "systems/a", "--system", "geohash", "--remove", "--no-dry-run"])
    assert schema.parse_article(vault / "systems" / "a.md", vault).list_field("systems") == ["Athena"]


def test_tag_takes_several_articles_and_bumps_their_dates(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", last_updated="2020-01-01")
    article("systems/b", last_updated="2020-01-01")
    runner.invoke(app, ["article", "tag", "systems/a", "systems/b", "--repo", "some-service", "--no-dry-run"])
    for slug in ("a", "b"):
        parsed = schema.parse_article(vault / "systems" / f"{slug}.md", vault)
        assert parsed.list_field("repos") == ["some-service"]
        assert parsed.date_field("last_updated") == date.today()


def test_tag_needs_at_least_one_value(article: ArticleWriter, vault: Path) -> None:
    article("systems/a")
    assert runner.invoke(app, ["article", "tag", "systems/a", "--no-dry-run"]).exit_code == 1
