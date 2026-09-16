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


def test_it_finds_a_cited_file_that_no_longer_exists(article: ArticleWriter, vault: Path, tmp_path: Path) -> None:
    # tmp_path stands in for the home directory, so the rule's home-rooted filter applies.
    article("systems/a", body=f"The real spec lives at `{tmp_path}/gone.md`.\n")
    (found,) = [f for f in check(vault, home=tmp_path) if f.rule == "cited-path-missing"]
    assert found.severity == WARN
    assert "gone.md" in found.detail


def test_a_cited_file_that_exists_is_clean(article: ArticleWriter, vault: Path, tmp_path: Path) -> None:
    # tmp_path stands in for the home directory, so the rule's home-rooted filter applies.
    real = tmp_path / "spec.md"
    real.write_text("here", encoding="utf-8")
    article("systems/a", body=f"The real spec lives at `{real}`.\n")
    assert [f for f in check(vault, home=tmp_path) if f.rule == "cited-path-missing"] == []


def test_it_ignores_things_that_look_like_paths_but_are_not(
    article: ArticleWriter, vault: Path, tmp_path: Path
) -> None:
    # Every one of these appeared in the real vault and none is a defect. Checking them
    # produced sixteen findings and zero real ones.
    body = (
        "Call `/permits/rates` on the registry.\n"
        "Run `/gaps-review` to sort the list.\n"
        "Scrape `/actuator/prometheus` for metrics.\n"
        "Inside the container, look in `/proc/1/root/tmp/`.\n"
        "Hit `/stats?executor=KDF_FILE` for pod counts.\n"
    )
    article("systems/a", body=body)
    assert [f for f in check(vault, home=tmp_path) if f.rule == "cited-path-missing"] == []


def test_a_tilde_path_is_expanded_before_checking(article: ArticleWriter, vault: Path) -> None:
    article("systems/a", body="See `~/definitely-not-a-real-file-9e3f.md`.\n")
    assert [f.rule for f in check(vault) if f.rule == "cited-path-missing"] == ["cited-path-missing"]


def test_the_same_missing_path_is_reported_once(article: ArticleWriter, vault: Path, tmp_path: Path) -> None:
    # tmp_path stands in for the home directory, so the rule's home-rooted filter applies.
    article("systems/a", body=f"See `{tmp_path}/gone.md`.\n\nAnd again: `{tmp_path}/gone.md`.\n")
    assert len([f for f in check(vault, home=tmp_path) if f.rule == "cited-path-missing"]) == 1


def test_a_cited_path_finding_points_at_the_right_line(article: ArticleWriter, vault: Path, tmp_path: Path) -> None:
    # tmp_path stands in for the home directory, so the rule's home-rooted filter applies.
    article("systems/a", body=f"First line.\n\nSee `{tmp_path}/gone.md`.\n")
    (found,) = [f for f in check(vault, home=tmp_path) if f.rule == "cited-path-missing"]
    on_disk = (vault / found.path).read_text().splitlines()
    assert "gone.md" in on_disk[found.line - 1]


def test_it_finds_a_slug_date_that_disagrees_with_created(article: ArticleWriter, vault: Path) -> None:
    # The date is load-bearing on exactly these articles, so a silent disagreement is
    # worse here than anywhere else.
    article("incidents/2026-06-25-a-thing", created="2026-09-16", type="incident")
    (found,) = [f for f in check(vault) if f.rule == "slug-date-mismatch"]
    assert found.severity == WARN
    assert "2026-06-25" in found.detail


def test_a_slug_date_that_agrees_is_clean(article: ArticleWriter, vault: Path) -> None:
    article("incidents/2026-06-25-a-thing", created="2026-06-25", type="incident")
    assert [f for f in check(vault) if f.rule == "slug-date-mismatch"] == []


def test_an_undated_slug_is_never_a_mismatch(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/some-procedure", created="2026-09-16")
    assert [f for f in check(vault) if f.rule == "slug-date-mismatch"] == []


def test_a_superseded_article_is_never_stale(article: ArticleWriter, vault: Path) -> None:
    # It is expected never to change again, so its age says nothing about its truth.
    article("research/old-plan", status="superseded", last_updated="2020-01-01")
    assert not [f for f in check(vault, today=date(2026, 9, 16)) if f.rule == "stale"]


def test_superseded_is_a_valid_status(article: ArticleWriter, vault: Path) -> None:
    article("research/old-plan", status="superseded")
    assert "frontmatter-invalid-status" not in _rules(check(vault), "research/old-plan.md")
