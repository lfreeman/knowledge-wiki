"""`kb lint` — the cheap pass, checked against deliberately planted defects."""

import json
from datetime import date
from pathlib import Path

from conftest import ArticleWriter
from typer.testing import CliRunner

from kb.cli import app
from kb.commands.lint import ERROR, WARN, Finding, check

runner = CliRunner()


def _rules(findings: list[Finding], path: str | None = None) -> set[str]:
    return {finding.rule for finding in findings if path is None or finding.path == path}


# --- the three defects the plan names as this command's acceptance criterion ---


def test_it_finds_a_bare_title_wikilink(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/target")
    article("guides/offender", body="See [[Target]] for the procedure.\n")
    (found,) = [f for f in check(vault) if f.rule == "link-bare-title"]
    assert found.severity == ERROR
    assert found.path == "guides/offender.md"
    assert "[[path/slug|Target]]" in found.detail


def test_it_finds_an_unescaped_pipe_in_a_table_row(article: ArticleWriter, vault: Path) -> None:
    body = "| Article | Note |\n|---|---|\n| [[runbooks/target|Target]] | see this |\n"
    article("runbooks/target")
    article("guides/offender", body=body)
    (found,) = [f for f in check(vault) if f.rule == "link-unescaped-pipe"]
    assert found.severity == ERROR
    assert "escape the pipe" in found.detail


def test_it_finds_a_dead_reference_path(article: ArticleWriter, vault: Path) -> None:
    article("reference/gone", type="reference", path="/no/such/place/at/all")
    (found,) = [f for f in check(vault) if f.rule == "reference-dead-path"]
    assert found.severity == ERROR
    assert found.path == "reference/gone.md"


# --- the rest of the cheap pass ---


def test_the_same_link_escaped_in_a_table_is_clean(article: ArticleWriter, vault: Path) -> None:
    body = "| Article |\n|---|\n| [[runbooks/target\\|Target]] |\n"
    article("runbooks/target", related=["[[guides/ok|Ok]]"])
    article("guides/ok", body=body)
    assert not [f for f in check(vault) if f.rule in {"link-unescaped-pipe", "link-bare-title", "link-broken"}]


def test_an_unescaped_pipe_outside_a_table_is_clean(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/target")
    article("guides/ok", body="See [[runbooks/target|Target]] for the procedure.\n")
    assert not [f for f in check(vault) if f.rule == "link-unescaped-pipe"]


def test_it_finds_a_link_to_a_nonexistent_article(article: ArticleWriter, vault: Path) -> None:
    article("guides/offender", related=["[[runbooks/never-written|Never Written]]"])
    (found,) = [f for f in check(vault) if f.rule == "link-broken"]
    assert found.severity == ERROR


def test_a_link_to_a_heading_inside_a_real_article_is_clean(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/target")
    article("guides/ok", body="See [[runbooks/target#Step 2|Step 2]].\n")
    assert not [f for f in check(vault) if f.rule == "link-broken"]


def test_a_live_reference_path_is_clean(article: ArticleWriter, vault: Path, tmp_path: Path) -> None:
    real = tmp_path / "somewhere" / "doc.md"
    real.parent.mkdir()
    real.write_text("the real document", encoding="utf-8")
    article("reference/live", type="reference", path=str(real))
    assert not [f for f in check(vault) if f.rule.startswith("reference-")]


def test_a_reference_article_with_no_path_is_an_error(article: ArticleWriter, vault: Path) -> None:
    article("reference/pathless", type="reference")
    assert "reference-missing-path" in _rules(check(vault), "reference/pathless.md")


def test_it_finds_a_missing_required_field(article: ArticleWriter, vault: Path) -> None:
    article("guides/nosummary", summary=None)
    (found,) = [f for f in check(vault) if f.rule == "frontmatter-missing-field"]
    assert found.detail == "missing required field summary"


def test_an_empty_required_field_counts_as_missing(article: ArticleWriter, vault: Path) -> None:
    article("guides/blank", summary='""')
    assert "frontmatter-missing-field" in _rules(check(vault), "guides/blank.md")


def test_it_finds_an_unknown_type_and_status(article: ArticleWriter, vault: Path) -> None:
    article("guides/odd", type="manifesto", status="draft")
    assert {"frontmatter-invalid-type", "frontmatter-invalid-status"} <= _rules(check(vault), "guides/odd.md")


def test_it_finds_a_malformed_date(article: ArticleWriter, vault: Path) -> None:
    article("guides/whenever", created='"last tuesday"')
    assert "frontmatter-invalid-date" in _rules(check(vault), "guides/whenever.md")


def test_it_finds_last_updated_before_created(article: ArticleWriter, vault: Path) -> None:
    article("guides/backwards", created="2026-05-01", last_updated="2026-04-01")
    assert "frontmatter-date-order" in _rules(check(vault), "guides/backwards.md")


def test_it_finds_a_scalar_where_a_list_belongs(article: ArticleWriter, vault: Path) -> None:
    article("guides/scalar", repos="just-one-repo")
    assert "frontmatter-invalid-list" in _rules(check(vault), "guides/scalar.md")


def test_it_finds_two_articles_sharing_a_title(article: ArticleWriter, vault: Path) -> None:
    article("guides/first", title="The Same Thing")
    article("systems/second", title="the same thing")
    found = [f for f in check(vault) if f.rule == "duplicate-title"]
    assert {f.path for f in found} == {"guides/first.md", "systems/second.md"}


def test_it_finds_an_orphan(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/linked-to")
    article("guides/links-out", related=["[[runbooks/linked-to|Linked To]]"])
    orphans = {f.path for f in check(vault) if f.rule == "orphan"}
    assert orphans == {"guides/links-out.md"}


def test_it_finds_a_stale_article(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/old", last_updated="2026-01-01", repos=["some-service"])
    (found,) = [f for f in check(vault, today=date(2026, 9, 14)) if f.rule == "stale"]
    assert found.severity == WARN
    assert "check it against some-service" in found.detail


def test_a_stale_article_with_no_repos_says_so(article: ArticleWriter, vault: Path) -> None:
    article("incidents/2026-01-01-old", last_updated="2026-01-01")
    (found,) = [f for f in check(vault, today=date(2026, 9, 14)) if f.rule == "stale"]
    assert "nothing can auto-check it" in found.detail


def test_an_active_article_is_never_stale(article: ArticleWriter, vault: Path) -> None:
    # An active article mutates every session, so its age says nothing about its truth.
    article("learning/a-plan", status="active", type="learning", last_updated="2020-01-01")
    assert not [f for f in check(vault, today=date(2026, 9, 14)) if f.rule == "stale"]


def test_a_recent_article_is_not_stale(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/fresh", last_updated="2026-08-01")
    assert not [f for f in check(vault, today=date(2026, 9, 14)) if f.rule == "stale"]


def test_it_warns_about_an_article_in_an_undefined_directory(article: ArticleWriter, vault: Path) -> None:
    article("inbox/stray", type="concept")
    assert "unknown-directory" in _rules(check(vault), "inbox/stray.md")


def test_it_warns_when_a_type_sits_in_the_wrong_directory(article: ArticleWriter, vault: Path) -> None:
    article("guides/misfiled", type="runbook")
    assert "type-directory-mismatch" in _rules(check(vault), "guides/misfiled.md")


def test_a_type_with_no_home_directory_is_not_a_mismatch(article: ArticleWriter, vault: Path) -> None:
    article("systems/an-idea", type="concept")
    assert "type-directory-mismatch" not in _rules(check(vault), "systems/an-idea.md")


def test_an_unreadable_article_is_a_finding_not_a_crash(article: ArticleWriter, vault: Path) -> None:
    article("guides/good", related=["[[guides/good|Good]]"])
    (vault / "guides" / "bad.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (found,) = [f for f in check(vault) if f.rule == "frontmatter-unreadable"]
    assert found.path == "guides/bad.md"


def test_a_clean_vault_reports_nothing(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/a", related=["[[systems/b|B]]"], last_updated=date.today().isoformat())
    article("systems/b", related=["[[runbooks/a|A]]"], last_updated=date.today().isoformat())
    assert check(vault) == []


# --- the command wrapper ---


def test_the_command_exits_1_when_it_found_an_error(article: ArticleWriter, vault: Path) -> None:
    article("guides/offender", body="See [[Bare Title]].\n")
    assert runner.invoke(app, ["lint"]).exit_code == 1


def test_the_command_exits_0_on_warnings_alone(article: ArticleWriter, vault: Path) -> None:
    article("guides/lonely")
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0
    assert "orphan" in result.output


def test_a_clean_vault_exits_0(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/a", related=["[[systems/b|B]]"], last_updated=date.today().isoformat())
    article("systems/b", related=["[[runbooks/a|A]]"], last_updated=date.today().isoformat())
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0
    assert "Clean" in result.output


def test_json_output_separates_errors_from_warnings(article: ArticleWriter, vault: Path) -> None:
    article("guides/offender", body="See [[Bare Title]].\n")
    payload = json.loads(runner.invoke(app, ["lint", "--json"]).output)
    rules = {finding["rule"]: finding["severity"] for finding in payload["findings"]}
    assert rules["link-bare-title"] == "error"
    assert rules["orphan"] == "warn"
    assert payload["errors"] == sum(1 for f in payload["findings"] if f["severity"] == "error")
    assert payload["warnings"] == sum(1 for f in payload["findings"] if f["severity"] == "warn")


def test_the_stale_threshold_is_settable(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/a", related=["[[systems/b|B]]"], last_updated=date.today().isoformat())
    article("systems/b", related=["[[runbooks/a|A]]"], last_updated=date.today().isoformat())
    payload = json.loads(runner.invoke(app, ["lint", "--json", "--stale-months", "0"]).output)
    assert {finding["rule"] for finding in payload["findings"]} == {"stale"}


def test_a_finding_location_is_a_clickable_path_and_line(article: ArticleWriter, vault: Path) -> None:
    article("guides/offender", body="First line.\n\nSee [[Bare Title]].\n")
    (found,) = [f for f in check(vault) if f.rule == "link-bare-title"]
    on_disk = (vault / found.path).read_text().splitlines()
    assert "[[Bare Title]]" in on_disk[found.line - 1]
