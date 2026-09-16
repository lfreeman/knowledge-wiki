"""`kb init`, `kb skill`, `kb doctor`, `kb schema` — the wiring, not the content."""

import json
import os
import time
from pathlib import Path
from typing import Any

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


def test_every_shipped_skill_declares_a_name_and_description() -> None:
    for name in config.SKILL_NAMES:
        text = (config.skill_source(name) / "SKILL.md").read_text()
        front, _, _ = schema.split_frontmatter(text)
        assert f"name: {name}" in front, f"{name}/SKILL.md declares the wrong name"
        description = [line for line in front.splitlines() if line.startswith("description:")]
        assert description and len(description[0]) > len("description: "), name


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


def test_skill_status_reports_every_link(skills_dir: Path) -> None:
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    payload = json.loads(runner.invoke(app, ["skill", "status", "--json"]).output)
    assert payload["installed"] == len(config.SKILL_NAMES)
    by_name = {row["name"]: row for row in payload["skills"]}
    assert set(by_name) == set(config.SKILL_NAMES)
    assert by_name["gap"]["target"] == str(config.skill_source("gap").resolve())


def test_install_links_every_shipped_skill(skills_dir: Path) -> None:
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    for name in config.SKILL_NAMES:
        assert (skills_dir / name).is_symlink(), f"{name} was not linked"


def test_doctor_warns_when_only_some_skills_are_linked(skills_dir: Path, vault: Path) -> None:
    runner.invoke(app, ["skill", "install", "--no-dry-run"])
    (skills_dir / "gap").unlink()
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "skill-links"]
    assert finding["status"] == "warn"
    assert "gap" in finding["detail"]


def test_the_skill_file_declares_a_name_and_a_description() -> None:
    text = (config.skill_source() / "SKILL.md").read_text()
    front, _, _ = schema.split_frontmatter(text)
    assert "name: capture" in front
    description = [line for line in front.splitlines() if line.startswith("description:")]
    assert description and len(description[0]) > len("description: ")


def test_no_skill_tells_claude_to_call_a_command_that_does_not_exist() -> None:
    # A skill naming a command the CLI does not have is a skill that fails at the moment
    # it is needed, in a session nobody is watching.
    import re

    registered = {command.name for command in app.registered_commands}
    registered |= {group.name for group in app.registered_groups}
    for name in config.SKILL_NAMES:
        text = (config.skill_source(name) / "SKILL.md").read_text()
        named = {match.group(1) for match in re.finditer(r"^kb ([a-z]+)", text, re.MULTILINE)}
        named |= {match.group(1) for match in re.finditer(r"`kb ([a-z]+)", text)}
        assert named <= registered, f"{name}/SKILL.md names commands kb lacks: {sorted(named - registered)}"


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
    assert statuses["skill-links"] == "ok"


def test_doctor_warns_when_the_vault_is_not_a_git_repository(article: ArticleWriter, vault: Path) -> None:
    article("guides/a")
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "vault"]
    assert finding["status"] == "warn"
    assert "git" in finding["detail"]


def _index_finding(payload: dict[str, Any]) -> dict[str, Any]:
    (finding,) = [item for item in payload["findings"] if item["check"] == "index"]
    assert isinstance(finding, dict)
    return finding


def test_doctor_ignores_an_mtime_change_that_changed_no_content(
    article: ArticleWriter, vault: Path
) -> None:
    # A rebase, a checkout or a fresh clone rewrites every mtime without touching a
    # byte. An mtime-based check reports the whole vault as stale after each of them.
    article("guides/a")
    runner.invoke(app, ["index"])
    later = time.time() + 10
    for path in (vault / "guides" / "a.md", vault / schema.INDEX_FILE, vault / schema.BACKLINKS_FILE):
        os.utime(path, (later, later))
    assert _index_finding(json.loads(runner.invoke(app, ["doctor", "--json"]).output))["status"] == "ok"


def test_doctor_warns_when_an_article_changed_after_the_last_index(
    article: ArticleWriter, vault: Path
) -> None:
    article("guides/a")
    runner.invoke(app, ["index"])
    article("guides/b")
    finding = _index_finding(json.loads(runner.invoke(app, ["doctor", "--json"]).output))
    assert finding["status"] == "warn"
    assert schema.INDEX_FILE in finding["detail"]


def test_doctor_warns_when_only_the_backlinks_file_drifted(article: ArticleWriter, vault: Path) -> None:
    article("guides/a")
    runner.invoke(app, ["index"])
    (vault / schema.BACKLINKS_FILE).write_text('{"guides/a": ["invented/source"]}\n', encoding="utf-8")
    finding = _index_finding(json.loads(runner.invoke(app, ["doctor", "--json"]).output))
    assert finding["status"] == "warn"
    assert schema.BACKLINKS_FILE in finding["detail"]


def test_doctor_warns_when_a_generated_file_is_missing(article: ArticleWriter, vault: Path) -> None:
    article("guides/a")
    runner.invoke(app, ["index"])
    (vault / schema.BACKLINKS_FILE).unlink()
    finding = _index_finding(json.loads(runner.invoke(app, ["doctor", "--json"]).output))
    assert finding["status"] == "warn"
    assert "absent" in finding["detail"]


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


def test_repo_root_defaults_and_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    from kb import config as kb_config

    monkeypatch.delenv("KB_REPO_ROOT", raising=False)
    assert kb_config.load_config().repo_root == Path.home() / "workspace"
    monkeypatch.setenv("KB_REPO_ROOT", "/somewhere/else")
    assert kb_config.load_config().repo_root == Path("/somewhere/else")


def test_repo_resolves_a_repos_name_to_a_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    from kb import config as kb_config

    monkeypatch.setenv("KB_REPO_ROOT", "/checkouts")
    assert kb_config.load_config().repo("some-service") == Path("/checkouts/some-service")


def test_init_keeps_repo_root_in_the_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kb import config as kb_config

    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path / "checkouts"))
    runner.invoke(app, ["init", "--vault", str(tmp_path / "v")])
    assert json.loads(kb_config.config_file().read_text())["repo_root"] == str(tmp_path / "checkouts")


def test_doctor_warns_when_the_repo_root_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path / "nope"))
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    (finding,) = [item for item in payload["findings"] if item["check"] == "repo-root"]
    assert finding["status"] == "warn"


def test_no_skill_documents_an_option_that_does_not_exist() -> None:
    """The skills publish exhaustive option tables, which go stale the moment a flag moves.

    This is the same failure as naming a command that does not exist: it surfaces at the
    moment the skill is needed, in a session nobody is watching.
    """
    import inspect
    import re

    from kb.commands import adopt, article, gap, index, lint, search

    declared: set[str] = {"--json", "--dry-run", "--no-dry-run", "--help"}
    for module in (adopt, article, gap, index, lint, search):
        source = inspect.getsource(module)
        declared |= set(re.findall(r'typer\.Option\(\s*"(--[a-z][a-z0-9-]*)', source))
        for pair in re.findall(r'"(--[a-z][a-z0-9-]*/--[a-z][a-z0-9-]*)"', source):
            declared |= set(pair.split("/"))

    for name in config.SKILL_NAMES:
        text = (config.skill_source(name) / "SKILL.md").read_text()
        # Only flags written as code spans in the option tables and examples.
        used = set(re.findall(r"`(--[a-z][a-z0-9-]*)`", text))
        used |= set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", text))
        unknown = {flag for flag in used if flag not in declared}
        assert not unknown, f"{name}/SKILL.md documents flags kb does not have: {sorted(unknown)}"
