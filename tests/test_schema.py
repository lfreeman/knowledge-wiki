"""The parser half of SCHEMA.md: frontmatter, wikilinks, and what counts as an article."""

from pathlib import Path

import pytest
from conftest import ArticleWriter

from kb import schema
from kb.errors import ArticleError


def test_frontmatter_splits_into_yaml_body_and_offset() -> None:
    front, body, offset = schema.split_frontmatter("---\ntitle: A\n---\n\nBody\n")
    assert front == "title: A"
    assert body == "\nBody"
    assert offset == 3


def test_a_file_without_frontmatter_is_not_an_article() -> None:
    with pytest.raises(ArticleError, match="does not start with ---"):
        schema.split_frontmatter("# Just a heading\n")


def test_unclosed_frontmatter_is_reported_as_such() -> None:
    with pytest.raises(ArticleError, match="never closed"):
        schema.split_frontmatter("---\ntitle: A\n\nBody\n")


def test_an_unquoted_summary_containing_a_colon_is_a_parse_error(vault: Path) -> None:
    # The reason this is worth a test: a hand-rolled "split on the first colon" parser
    # accepts this silently and stores a truncated summary.
    path = vault / "guides" / "broken.md"
    path.write_text("---\ntitle: A\nsummary: Note: this breaks YAML\n---\n\nBody\n", encoding="utf-8")
    with pytest.raises(ArticleError, match="not valid YAML"):
        schema.parse_article(path, vault)


def test_parse_article_records_slug_and_directory(article: ArticleWriter, vault: Path) -> None:
    parsed = schema.parse_article(article("runbooks/restarting-a-thing"), vault)
    assert parsed.slug == "runbooks/restarting-a-thing"
    assert parsed.directory == "runbooks"
    assert parsed.title == "Restarting A Thing"


def test_a_quoted_and_a_bare_date_parse_the_same(article: ArticleWriter, vault: Path) -> None:
    bare = schema.parse_article(article("guides/bare", created="2026-03-04"), vault)
    quoted = schema.parse_article(article("guides/quoted", created='"2026-03-04"'), vault)
    assert bare.date_field("created") == quoted.date_field("created")


def test_a_full_wikilink_yields_target_and_alias() -> None:
    (link,) = schema.wikilinks("See [[runbooks/a-slug|A Title]] for more.")
    assert (link.target, link.alias, link.is_bare, link.escaped) == ("runbooks/a-slug", "A Title", False, False)


def test_a_bare_wikilink_has_no_alias() -> None:
    (link,) = schema.wikilinks("See [[A Title]].")
    assert link.is_bare
    assert link.target == "A Title"


def test_an_escaped_pipe_is_recognised_as_escaped() -> None:
    (link,) = schema.wikilinks("| [[runbooks/a-slug\\|A Title]] | stable |")
    assert link.escaped
    assert link.in_table_row
    assert link.target == "runbooks/a-slug"


def test_a_link_outside_a_table_is_not_marked_as_in_a_table() -> None:
    (link,) = schema.wikilinks("See [[runbooks/a-slug|A Title]].")
    assert not link.in_table_row


def test_link_line_numbers_point_at_the_real_file_position(article: ArticleWriter, vault: Path) -> None:
    parsed = schema.parse_article(
        article("guides/linked", body="First line.\n\nSee [[runbooks/a-slug|A Title]].\n"), vault
    )
    (found,) = [link for link in parsed.links() if link.line > 0]
    on_disk = parsed.path.read_text().splitlines()
    assert on_disk[found.line - 1].strip() == "See [[runbooks/a-slug|A Title]]."


def test_related_links_are_found_alongside_body_links(article: ArticleWriter, vault: Path) -> None:
    parsed = schema.parse_article(
        article("guides/both", body="See [[systems/b|B]].", related=["[[runbooks/a|A]]"]), vault
    )
    assert {link.target for link in parsed.links()} == {"runbooks/a", "systems/b"}


def test_generated_files_and_raw_entries_are_not_articles(article: ArticleWriter, vault: Path) -> None:
    article("guides/real")
    (vault / schema.INDEX_FILE).write_text("# Knowledge Index\n", encoding="utf-8")
    (vault / schema.RAW_DIRECTORY / "entries" / "entry-1.md").write_text("---\nid: x\n---\ntext\n", encoding="utf-8")
    (vault / "2026-09-13.md").write_text("", encoding="utf-8")
    assert [path.name for path in schema.article_paths(vault)] == ["real.md"]


def test_a_dotted_directory_is_skipped(article: ArticleWriter, vault: Path) -> None:
    article("guides/real")
    hidden = vault / ".obsidian" / "notes"
    hidden.mkdir(parents=True)
    (hidden / "scratch.md").write_text("---\ntitle: X\n---\n", encoding="utf-8")
    assert [path.name for path in schema.article_paths(vault)] == ["real.md"]


def test_one_unreadable_article_does_not_abort_the_others(article: ArticleWriter, vault: Path) -> None:
    article("guides/good")
    (vault / "guides" / "bad.md").write_text("no frontmatter here\n", encoding="utf-8")
    articles, failures = schema.load_vault(vault)
    assert [item.slug for item in articles] == ["guides/good"]
    assert [path.name for path, _ in failures] == ["bad.md"]


def test_the_type_vocabulary_matches_the_shipped_schema_document() -> None:
    # SCHEMA.md is the specification; schema.py is its executable half. If they drift,
    # the rules the model reads stop matching the rules lint enforces.
    text = (Path(__file__).resolve().parents[1] / "src" / "kb" / "SCHEMA.md").read_text()
    for name in schema.DIRECTORIES:
        assert f"  {name}/" in text, f"SCHEMA.md §1 does not list the {name}/ directory"
    for value in schema.TYPES:
        assert value in text, f"SCHEMA.md does not mention the {value} type"
    for name in schema.REQUIRED_FIELDS:
        assert name in text, f"SCHEMA.md does not mention the required field {name}"
