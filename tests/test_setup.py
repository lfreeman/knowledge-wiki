"""`kb init`, `kb skill`, `kb doctor`, `kb schema` — the wiring, not the content."""

import json
from pathlib import Path

import pytest
from conftest import ArticleWriter
from typer.testing import CliRunner

from kb import config, schema
from kb.cli import app

runner = CliRunner()


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every test off the real ~/.claude/skills."""
    directory = tmp_path / "claude-skills"
    directory.mkdir()
    monkeypatch.setattr(config, "CLAUDE_SKILLS_DIR", directory)
    return directory


# --- init ---


def test_init_creates_every_directory_the_schema_defines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "new-vault"
    monkeypatch.setenv("KB_VAULT", str(root))
    assert runner.invoke(app, ["init"]).exit_code == 0
    for name in schema.DIRECTORIES:
        assert (root / name).is_dir(), f"{name}/ was not created"
    assert (root / schema.RAW_DIRECTORY / "entries").is_dir()


def test_init_writes_the_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "new-vault"
    monkeypatch.setenv("KB_VAULT", str(root))
    runner.invoke(app, ["init"])
    assert json.loads(config.config_file().read_text())["vault"] == str(root)


def test_init_takes_an_explicit_vault_path(tmp_path: Path) -> None:
    root = tmp_path / "elsewhere"
    payload = json.loads(runner.invoke(app, ["init", "--vault", str(root), "--json"]).output)
    assert payload["vault"] == str(root)
    assert root.is_dir()


def test_init_generates_an_index_so_the_vault_is_immediately_valid(tmp_path: Path) -> None:
    root = tmp_path / "new-vault"
    runner.invoke(app, ["init", "--vault", str(root)])
    assert (root / schema.INDEX_FILE).is_file()
    assert (root / schema.BACKLINKS_FILE).is_file()


def test_init_does_not_copy_the_schema_into_the_vault(tmp_path: Path) -> None:
    # Two copies of the rules drift, which is the failure the whole design is built against.
    root = tmp_path / "new-vault"
    runner.invoke(app, ["init", "--vault", str(root)])
    assert not (root / "SCHEMA.md").exists()


def test_init_is_safe_to_run_twice(tmp_path: Path, article: ArticleWriter, vault: Path) -> None:
    article("guides/existing")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert (vault / "guides" / "existing.md").exists()


def test_init_does_not_install_the_skill(tmp_path: Path, skills_dir: Path) -> None:
    runner.invoke(app, ["init", "--vault", str(tmp_path / "new-vault")])
    assert not (skills_dir / config.SKILL_NAME).exists()


# --- skill ---


def test_skill_install_dry_run_creates_nothing(skills_dir: Path) -> None:
    result = runner.invoke(app, ["skill", "install"])
    assert result.exit_code == 0
    assert not (skills_dir / config.SKILL_NAME).exists()


def test_skill_install_creates_a_symlink_to_the_repo(skills_dir: Path) -> None:
    assert runner.invoke(app, ["skill", "install", "--no-dry-run"]).exit_code == 0
    link = skills_dir / config.SKILL_NAME
    assert link.is_symlink()
    assert link.resolve() == config.skill_source().resolve()


def test_skill_install_refuses_to_replace_a_real_directory(skills_dir: Path) -> None:
    occupied = skills_dir / config.SKILL_NAME
    occupied.mkdir()
    (occupied / "SKILL.md").write_text("someone else's skill", encoding="utf-8")
    assert runner.invoke(app, ["skill", "install", "--no-dry-run"]).exit_code == 1
    assert (occupied / "SKILL.md").read_text() == "someone else's skill"


def test_skill_install_repoints_a_stale_symlink(skills_dir: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (skills_dir / config.SKILL_NAME).symlink_to(elsewhere)
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    assert (skills_dir / config.SKILL_NAME).resolve() == config.skill_source().resolve()


def test_skill_status_reports_the_link_target(skills_dir: Path) -> None:
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    payload = json.loads(runner.invoke(app, ["skill", "status", "--json"]).output)
    assert payload["installed"] is True
    assert payload["target"] == str(config.skill_source().resolve())


def test_the_skill_file_declares_a_name_and_a_description() -> None:
    text = (config.skill_source() / "SKILL.md").read_text()
    front, _, _ = schema.split_frontmatter(text)
    assert "name: capture" in front
    description = [line for line in front.splitlines() if line.startswith("description:")]
    assert description and len(description[0]) > len("description: ")


def test_the_skill_only_tells_claude_to_call_commands_that_exist() -> None:
    # A skill naming a command the CLI does not have is a skill that fails at the moment
    # it is needed, in a session nobody is watching.
    import re

    text = (config.skill_source() / "SKILL.md").read_text()
    named = {match.group(1) for match in re.finditer(r"^kb ([a-z]+)", text, re.MULTILINE)}
    named |= {match.group(1) for match in re.finditer(r"`kb ([a-z]+)", text)}
    registered = {command.name for command in app.registered_commands}
    registered |= {group.name for group in app.registered_groups}
    assert named <= registered, f"SKILL.md names commands kb does not have: {sorted(named - registered)}"


# --- doctor ---


def test_doctor_reports_ok_on_a_healthy_vault(article: ArticleWriter, vault: Path, skills_dir: Path) -> None:
    article("runbooks/a", related=["[[systems/b|B]]"], last_updated="2026-09-14")
    article("systems/b", related=["[[runbooks/a|A]]"], last_updated="2026-09-14")
    runner.invoke(app, ["init"])
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    statuses = {finding["check"]: finding["status"] for finding in payload["findings"]}
    assert statuses["vault"] in {"ok", "warn"}
    assert statuses["index"] == "ok"
    assert statuses["schema"] == "ok"
    assert statuses["skill-link"] == "ok"


def test_doctor_warns_when_the_vault_is_not_a_git_repository(article: ArticleWriter, vault: Path) -> None:
    article("guides/a")
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "vault"]
    assert finding["status"] == "warn"
    assert "git" in finding["detail"]


def test_doctor_warns_when_an_article_changed_after_the_last_index(
    article: ArticleWriter, vault: Path
) -> None:
    article("guides/a")
    runner.invoke(app, ["index"])
    import os
    import time

    later = time.time() + 10
    os.utime(vault / "guides" / "a.md", (later, later))
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "index"]
    assert finding["status"] == "warn"
    assert "a.md" in finding["detail"]


def test_doctor_reports_a_missing_vault_as_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_VAULT", str(tmp_path / "nope"))
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    statuses = {finding["check"]: finding["status"] for finding in payload["findings"]}
    assert statuses["vault"] == "crit"
    assert statuses["index"] == "skipped"
    assert payload["status"] == "crit"


def test_doctor_surfaces_lint_errors(article: ArticleWriter, vault: Path) -> None:
    article("guides/offender", body="See [[Bare Title]].\n")
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "lint"]
    assert finding["status"] == "crit"


def test_doctor_reports_an_unreadable_article(article: ArticleWriter, vault: Path) -> None:
    article("guides/good")
    (vault / "guides" / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "vault"]
    assert finding["status"] == "crit"
    assert "bad.md" in finding["detail"]


# --- schema ---


def test_schema_prints_the_shipped_rules() -> None:
    output = runner.invoke(app, ["schema"]).output
    assert "# SCHEMA.md" in output
    assert "[[path/slug|Display Title]]" in output


def test_schema_path_points_inside_the_installed_package() -> None:
    output = runner.invoke(app, ["schema", "--path"]).output.strip()
    assert output.endswith("kb/SCHEMA.md")
    assert Path(output).is_file()
