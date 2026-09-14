"""`kb index` — the derived files, and the rules that keep them readable."""

import json
import re
from pathlib import Path

from conftest import ArticleWriter
from typer.testing import CliRunner

from kb import schema
from kb.cli import app
from kb.commands.index import rebuild

runner = CliRunner()


def _rows(text: str) -> list[str]:
    """Every table body row in a rendered index."""
    return [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("|---")][1:]


def test_every_article_appears_exactly_once(article: ArticleWriter, vault: Path) -> None:
    # The plan's stated acceptance criterion for this command.
    slugs = ["runbooks/a-runbook", "systems/a-system", "guides/a-guide", "incidents/2026-01-01-a-thing"]
    for slug in slugs:
        article(slug)
    rebuild(vault)
    text = (vault / schema.INDEX_FILE).read_text()
    for slug in slugs:
        assert text.count(f"[[{slug}\\|") == 1, f"{slug} does not appear exactly once"
    assert len([row for row in _rows(text) if "[[" in row]) == len(slugs)


def test_articles_are_grouped_under_their_directory(article: ArticleWriter, vault: Path) -> None:
    for name in ("runbooks", "systems", "guides"):
        article(f"{name}/an-article")
    rebuild(vault)
    text = (vault / schema.INDEX_FILE).read_text()
    section = ""
    seen: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").split("/")[0]
        elif "[[" in line and line.startswith("| "):
            slug = line.split("[[")[1].split("\\|")[0]
            seen[slug] = section
    assert seen == {
        "guides/an-article": "guides",
        "runbooks/an-article": "runbooks",
        "systems/an-article": "systems",
    }


def test_an_empty_directory_renders_as_empty(vault: Path) -> None:
    rebuild(vault)
    text = (vault / schema.INDEX_FILE).read_text()
    assert text.count("*(empty)*") == len(schema.DIRECTORIES)


def test_every_wikilink_in_the_index_carries_a_path_and_an_escaped_pipe(
    article: ArticleWriter, vault: Path
) -> None:
    article("runbooks/a-runbook")
    rebuild(vault)
    links = [
        found
        for row in _rows((vault / schema.INDEX_FILE).read_text())
        for found in re.findall(r"\[\[(.+?)\]\]", row)
    ]
    assert links
    for link in links:
        assert "\\|" in link, f"{link} does not escape its pipe inside a table"
        assert "/" in link.split("\\|")[0], f"{link} is a bare title link"


def test_a_pipe_in_a_summary_is_escaped_rather_than_splitting_the_row(
    article: ArticleWriter, vault: Path
) -> None:
    article("guides/piped", summary='"Reads a | b from the stream."')
    rebuild(vault)
    (row,) = [line for line in _rows((vault / schema.INDEX_FILE).read_text()) if "guides/piped" in line]
    assert row.count("|") - row.count("\\|") == 5, "a raw pipe leaked into the row and added a column"


def test_a_multiline_summary_is_flattened_onto_one_row(article: ArticleWriter, vault: Path) -> None:
    article("guides/wrapped", summary='"First part.\n  Second part."')
    rebuild(vault)
    (row,) = [line for line in _rows((vault / schema.INDEX_FILE).read_text()) if "guides/wrapped" in line]
    assert "First part. Second part." in row


def test_rows_are_minimal_and_unpadded(article: ArticleWriter, vault: Path) -> None:
    # Column-aligned rows invite an editor to reflow them, and reflowing pushes the
    # alignment padding inside the wikilinks and breaks them.
    article("guides/a-guide", systems=["Alpha"])
    rebuild(vault)
    for row in _rows((vault / schema.INDEX_FILE).read_text()):
        for cell in re.split(r"(?<!\\)\|", row)[1:-1]:
            assert cell == f" {cell.strip()} ", f"cell carries alignment padding: {cell!r}"


def test_an_active_article_is_marked_active(article: ArticleWriter, vault: Path) -> None:
    article("learning/a-plan", status="active")
    rebuild(vault)
    (row,) = [line for line in _rows((vault / schema.INDEX_FILE).read_text()) if "learning/a-plan" in line]
    assert "**active**" in row


def test_backlinks_record_who_points_at_what(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/target")
    article("systems/pointer", related=["[[runbooks/target|Target]]"])
    article("guides/also", body="See [[runbooks/target|Target]].")
    rebuild(vault)
    assert json.loads((vault / schema.BACKLINKS_FILE).read_text()) == {
        "runbooks/target": ["guides/also", "systems/pointer"]
    }


def test_a_broken_link_produces_no_backlink(article: ArticleWriter, vault: Path) -> None:
    article("systems/pointer", related=["[[runbooks/does-not-exist|Nope]]"])
    rebuild(vault)
    assert json.loads((vault / schema.BACKLINKS_FILE).read_text()) == {}


def test_an_article_does_not_backlink_itself(article: ArticleWriter, vault: Path) -> None:
    article("systems/self", body="See [[systems/self|Self]].")
    rebuild(vault)
    assert json.loads((vault / schema.BACKLINKS_FILE).read_text()) == {}


def test_rebuilding_overwrites_a_hand_edited_index(article: ArticleWriter, vault: Path) -> None:
    article("guides/a-guide")
    rebuild(vault)
    (vault / schema.INDEX_FILE).write_text("someone reflowed this\n", encoding="utf-8")
    rebuild(vault)
    assert "[[guides/a-guide" in (vault / schema.INDEX_FILE).read_text()


def test_rebuilding_twice_produces_identical_output(article: ArticleWriter, vault: Path) -> None:
    article("guides/a-guide")
    rebuild(vault)
    first = (vault / schema.INDEX_FILE).read_text()
    rebuild(vault)
    assert (vault / schema.INDEX_FILE).read_text() == first


def test_an_unknown_directory_is_indexed_rather_than_dropped(article: ArticleWriter, vault: Path) -> None:
    article("inbox/stray", type="concept")
    rebuild(vault)
    text = (vault / schema.INDEX_FILE).read_text()
    assert "## inbox/ — not a directory SCHEMA.md defines" in text
    assert "[[inbox/stray\\|" in text


def test_an_unreadable_article_is_reported_and_the_rest_still_index(
    article: ArticleWriter, vault: Path
) -> None:
    article("guides/good")
    (vault / "guides" / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    result = rebuild(vault)
    assert result.articles == 1
    assert [path.name for path, _ in result.failures] == ["bad.md"]
    assert "[[guides/good\\|" in (vault / schema.INDEX_FILE).read_text()


def test_dry_run_writes_nothing(article: ArticleWriter, vault: Path) -> None:
    article("guides/a-guide")
    result = runner.invoke(app, ["index", "--dry-run"])
    assert result.exit_code == 0
    assert not (vault / schema.INDEX_FILE).exists()
    assert not (vault / schema.BACKLINKS_FILE).exists()


def test_the_command_writes_by_default(article: ArticleWriter, vault: Path) -> None:
    article("guides/a-guide")
    assert runner.invoke(app, ["index"]).exit_code == 0
    assert (vault / schema.INDEX_FILE).exists()


def test_json_output_is_parseable_and_counts_what_it_wrote(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/target")
    article("systems/pointer", related=["[[runbooks/target|Target]]"])
    payload = json.loads(runner.invoke(app, ["index", "--json"]).output)
    assert payload["articles"] == 2
    assert payload["backlinks"] == 1
    assert payload["unreadable"] == []


def test_a_missing_vault_is_a_one_line_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["index"], env={"KB_VAULT": str(tmp_path / "nope")})
    assert result.exit_code == 1
