"""`kb adopt` — the mechanical half of the adoption procedure."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kb import schema
from kb.cli import app
from kb.commands.adopt import examine

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository named `some-service` with a docs directory."""
    root = tmp_path / "some-service"
    (root / "docs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


# --- inspect: the evidence, nothing decided ---


def test_inspect_reports_when_a_document_names_its_own_repo(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n\nThis describes some-service's request path.\n", encoding="utf-8")
    result = examine(doc)
    assert result.repo_name == "some-service"
    assert result.names_own_repo is True


def test_inspect_reports_when_a_document_never_names_its_own_repo(repo: Path) -> None:
    doc = repo / "docs" / "jvm-runbook.md"
    doc.write_text("# JVM Runbook\n\nApplies to any JVM workload.\n", encoding="utf-8")
    assert examine(doc).names_own_repo is False


def test_inspect_reports_whether_the_repo_lists_the_document(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("Project docs: docs/design.md\n", encoding="utf-8")
    assert examine(doc).listed_in_repo_docs == ["CLAUDE.md"]


def test_inspect_finds_relative_links_that_resolve(repo: Path) -> None:
    (repo / "docs" / "other.md").write_text("# Other\n", encoding="utf-8")
    doc = repo / "docs" / "design.md"
    doc.write_text("See [Other](other.md) and [Nothing](nowhere.md) and [Web](https://example.com).\n", "utf-8")
    targets = [reference.path for reference in examine(doc).outbound_relative]
    assert targets == ["other.md"]


def test_inspect_finds_inbound_references(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    (repo / "README.md").write_text("Read docs/design.md first.\n", encoding="utf-8")
    inbound = examine(doc).inbound
    assert [Path(reference.path).name for reference in inbound] == ["README.md"]
    assert inbound[0].line == 1


def test_inspect_does_not_count_the_document_as_its_own_inbound_reference(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n\nThis file is design.md.\n", encoding="utf-8")
    assert examine(doc).inbound == []


def test_inspect_skips_vendor_directories(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    vendored = repo / "node_modules" / "thing"
    vendored.mkdir(parents=True)
    (vendored / "copy.md").write_text("design.md\n", encoding="utf-8")
    assert examine(doc).inbound == []


def test_inspect_changes_nothing(repo: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n\nSee [Other](other.md).\n", encoding="utf-8")
    before = doc.read_text()
    runner.invoke(app, ["adopt", "inspect", str(doc), "--json"])
    assert doc.read_text() == before


# --- move: the homeless document ---


def test_move_is_a_preview_by_default(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "jvm-runbook.md"
    doc.write_text("# JVM Runbook\n\nSteps.\n", encoding="utf-8")
    result = runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "Triage steps."])
    assert result.exit_code == 0
    assert doc.exists()
    assert not (vault / "runbooks" / "jvm-runbook.md").exists()


def test_move_writes_the_article_and_removes_the_source(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "jvm-runbook.md"
    doc.write_text("# JVM Runbook\n\nSteps.\n", encoding="utf-8")
    result = runner.invoke(
        app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "Triage steps.", "--no-dry-run"]
    )
    assert result.exit_code == 0
    assert not doc.exists()
    parsed = schema.parse_article(vault / "runbooks" / "jvm-runbook.md", vault)
    assert parsed.title == "JVM Runbook"
    assert parsed.type == "runbook"
    assert "Steps." in parsed.body


def test_move_can_leave_a_symlink_behind_for_inbound_references(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "jvm-runbook.md"
    doc.write_text("# JVM Runbook\n\nSteps.\n", encoding="utf-8")
    runner.invoke(
        app,
        ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--source", "symlink", "--no-dry-run"],
    )
    assert doc.is_symlink()
    assert doc.resolve() == (vault / "runbooks" / "jvm-runbook.md").resolve()
    assert "Steps." in doc.read_text()


def test_move_can_keep_the_source_untouched(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "jvm-runbook.md"
    doc.write_text("# JVM Runbook\n\nSteps.\n", encoding="utf-8")
    runner.invoke(
        app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--source", "keep", "--no-dry-run"]
    )
    assert doc.is_file() and not doc.is_symlink()


def test_move_absolutises_relative_links(repo: Path, vault: Path) -> None:
    (repo / "docs" / "other.md").write_text("# Other\n", encoding="utf-8")
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n\nSee [Other](other.md#step-2) and [Web](https://example.com).\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--no-dry-run"])
    body = (vault / "runbooks" / "runbook.md").read_text()
    assert f"({(repo / 'docs' / 'other.md').resolve()}#step-2)" in body
    assert "(https://example.com)" in body


def test_move_leaves_a_relative_link_that_resolves_to_nothing_alone(repo: Path, vault: Path) -> None:
    # It was never a path into this repo, so rewriting it would be vandalism.
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n\nSee [Nothing](nowhere.md).\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--no-dry-run"])
    assert "[Nothing](nowhere.md)" in (vault / "runbooks" / "runbook.md").read_text()


def test_move_keeps_existing_frontmatter_fields(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "runbook.md"
    doc.write_text("---\ntitle: Kept Title\nsystems: [Alpha]\n---\n\nBody.\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--no-dry-run"])
    parsed = schema.parse_article(vault / "runbooks" / "runbook.md", vault)
    assert parsed.title == "Kept Title"
    assert parsed.list_field("systems") == ["Alpha"]


def test_move_to_learning_marks_live_state_active(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "plan.md"
    doc.write_text("# Plan\n\nProgress log.\n", encoding="utf-8")
    runner.invoke(
        app,
        ["adopt", "move", str(doc), "--to", "learning", "--summary", "S", "--status", "active", "--no-dry-run"],
    )
    parsed = schema.parse_article(vault / "learning" / "plan.md", vault)
    assert parsed.is_active
    assert parsed.type == "learning"


def test_move_rejects_a_directory_the_schema_does_not_define(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n", encoding="utf-8")
    result = runner.invoke(app, ["adopt", "move", str(doc), "--to", "inbox", "--summary", "S", "--no-dry-run"])
    assert result.exit_code == 1
    assert doc.exists()


def test_move_refuses_to_overwrite_and_leaves_the_source_alone(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n", encoding="utf-8")
    (vault / "runbooks" / "runbook.md").write_text("---\ntitle: Already Here\n---\n\nBody.\n", encoding="utf-8")
    result = runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--no-dry-run"])
    assert result.exit_code == 1
    assert doc.exists()
    assert "Already Here" in (vault / "runbooks" / "runbook.md").read_text()


# --- point: the document that stays where it is ---


def test_point_writes_a_stub_and_moves_nothing(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n\nSeven hundred lines of real content.\n", encoding="utf-8")
    result = runner.invoke(
        app, ["adopt", "point", str(doc), "--summary", "What it covers.", "--repo", "some-service", "--no-dry-run"]
    )
    assert result.exit_code == 0
    assert doc.read_text() == "# Design\n\nSeven hundred lines of real content.\n"
    parsed = schema.parse_article(vault / "reference" / "design.md", vault)
    assert parsed.type == "reference"
    assert parsed.get("path") == str(doc.resolve())
    assert parsed.list_field("repos") == ["some-service"]


def test_a_pointer_stub_does_not_restate_the_document(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n\nSeven hundred lines of real content.\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "point", str(doc), "--summary", "What it covers.", "--no-dry-run"])
    body = schema.parse_article(vault / "reference" / "design.md", vault).body
    assert "Seven hundred lines" not in body
    assert str(doc.resolve()) in body


def test_point_can_point_at_a_directory(repo: Path, vault: Path) -> None:
    runner.invoke(app, ["adopt", "point", str(repo), "--title", "Some Service", "--summary", "S", "--no-dry-run"])
    assert schema.parse_article(vault / "reference" / "some-service.md", vault).get("path") == str(repo.resolve())


def test_point_is_a_preview_by_default(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "point", str(doc), "--summary", "S"])
    assert not (vault / "reference" / "design.md").exists()


def test_a_pointer_article_lints_clean(repo: Path, vault: Path) -> None:
    from kb.commands.lint import check

    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "point", str(doc), "--summary", "What it covers.", "--no-dry-run"])
    assert [f.rule for f in check(vault) if f.severity == "error"] == []


def test_move_json_reports_the_links_it_rewrote(repo: Path, vault: Path) -> None:
    (repo / "docs" / "other.md").write_text("# Other\n", encoding="utf-8")
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n\nSee [Other](other.md).\n", encoding="utf-8")
    payload = json.loads(
        runner.invoke(app, ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--json"]).output
    )
    assert payload["dry_run"] is True
    assert [reference["path"] for reference in payload["links_absolutised"]] == ["other.md"]


def test_inspect_searches_the_configured_repo_root_not_just_the_enclosing_repo(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reference that matters most is the one from a *different* repo, because that is
    # the one that breaks silently on a move. Searching only the enclosing repo missed it.
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    other = tmp_path / "other-service"
    other.mkdir()
    (other / "NOTES.md").write_text("See docs/design.md in the other repo.\n", encoding="utf-8")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    inbound = examine(doc).inbound
    assert [Path(reference.path).name for reference in inbound] == ["NOTES.md"]


def test_inspect_reports_which_roots_it_searched(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    assert str(tmp_path) in examine(doc).searched


def test_inspect_does_not_scan_a_root_twice(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The enclosing repo sits inside the repo root here, so it must not be listed as well.
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    (repo / "README.md").write_text("docs/design.md\n", encoding="utf-8")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    result = examine(doc)
    assert len(result.searched) == 1
    assert len(result.inbound) == 1


def test_inspect_flags_a_filename_that_other_files_also_use(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = repo / "docs" / "architecture.md"
    doc.write_text("# Architecture\n", encoding="utf-8")
    other = tmp_path / "other-service" / "wiki"
    other.mkdir(parents=True)
    (other / "architecture.md").write_text("# A different architecture doc\n", encoding="utf-8")
    (other / "index.md").write_text("See architecture.md\n", encoding="utf-8")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    result = examine(doc)
    assert result.ambiguous_name is True


def test_a_distinctive_filename_is_not_flagged(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = repo / "docs" / "hash-file-throughput-9e3f.md"
    doc.write_text("# Distinctive\n", encoding="utf-8")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    assert examine(doc).ambiguous_name is False


def test_move_writes_dates_unquoted(repo: Path, vault: Path) -> None:
    # A quoted date beside an unquoted one is noise in every later diff, and `adopt` had
    # the same bug `article` did: it passed the date through as a string.
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n", encoding="utf-8")
    runner.invoke(
        app,
        ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--created", "2026-05-11", "--no-dry-run"],
    )
    front, _, _ = schema.split_frontmatter((vault / "runbooks" / "runbook.md").read_text())
    assert "created: 2026-05-11" in front
    assert '"' not in front.split("created:")[1].splitlines()[0]


def test_point_writes_dates_unquoted(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "design.md"
    doc.write_text("# Design\n", encoding="utf-8")
    runner.invoke(app, ["adopt", "point", str(doc), "--summary", "S", "--no-dry-run"])
    front, _, _ = schema.split_frontmatter((vault / "reference" / "design.md").read_text())
    assert f"created: {date.today().isoformat()}" in front


def test_move_rejects_a_created_date_it_cannot_parse(repo: Path, vault: Path) -> None:
    doc = repo / "docs" / "runbook.md"
    doc.write_text("# Runbook\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["adopt", "move", str(doc), "--to", "runbooks", "--summary", "S", "--created", "whenever", "--no-dry-run"],
    )
    assert result.exit_code == 1
    assert doc.exists()
