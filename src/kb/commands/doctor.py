"""`kb doctor` — report what is and is not set up.

Doctor reports; it never repairs. A check whose input is already broken reports
`skipped` naming what blocked it, because an honest "could not run" beats quietly
reporting fewer problems than exist.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config, schema
from ..commands.index import render_backlinks, render_index
from ..commands.lint import ERROR, check
from ..errors import KbError
from ..output import JsonOption, console, emit_json, table

OK = "ok"
WARN = "warn"
CRIT = "crit"
SKIPPED = "skipped"

_STYLES = {OK: "green", WARN: "yellow", CRIT: "red", SKIPPED: "dim"}


@dataclass(frozen=True)
class Finding:
    """One check and what it found."""

    check: str
    status: str
    detail: str


def doctor(as_json: JsonOption = False) -> None:
    """Check the config, the vault, the generated files, and the skill link."""
    findings = _checks()
    if as_json:
        emit_json({"findings": [asdict(finding) for finding in findings], "status": _worst(findings)})
        return
    rendered = table("Check", "Status", "Detail")
    for finding in findings:
        rendered.add_row(finding.check, f"[{_STYLES[finding.status]}]{finding.status}[/]", finding.detail)
    console.print(rendered)


def _checks() -> list[Finding]:
    findings = [_config_dir()]
    settings, config_finding = _config_file()
    findings.append(config_finding)
    if settings is None:
        blocked = "config.json could not be read"
        findings += [
            Finding("vault", SKIPPED, blocked),
            Finding("index", SKIPPED, blocked),
            Finding("lint", SKIPPED, blocked),
        ]
    elif not settings.vault.is_dir():
        missing = f"{settings.vault} does not exist; run `kb init`"
        findings += [
            Finding("vault", CRIT, missing),
            Finding("index", SKIPPED, "no vault"),
            Finding("lint", SKIPPED, "no vault"),
        ]
    else:
        findings.append(_vault(settings.vault))
        findings.append(_index(settings.vault))
        findings.append(_lint(settings.vault))
    findings.append(_repo_root())
    findings.append(_schema())
    findings.append(_skill_link())
    return findings


def _config_dir() -> Finding:
    directory = config.config_dir()
    if directory.is_dir():
        return Finding("config-dir", OK, str(directory))
    return Finding("config-dir", WARN, f"{directory} does not exist yet; `kb init` creates it")


def _config_file() -> tuple[config.Config | None, Finding]:
    path = config.config_file()
    try:
        settings = config.load_config()
    except KbError as exc:
        return None, Finding("config-file", CRIT, str(exc))
    detail = str(path) if path.exists() else f"{path} absent; using defaults"
    return settings, Finding("config-file", OK, detail)


def _vault(vault: Path) -> Finding:
    """A vault that is not a git repository has no history and no off-machine copy."""
    articles, failures = schema.load_vault(vault)
    detail = f"{vault} ({len(articles)} article(s))"
    if failures:
        names = ", ".join(path.name for path, _ in failures)
        return Finding("vault", CRIT, f"{detail}; {len(failures)} unreadable: {names}")
    if not (vault / ".git").exists():
        return Finding("vault", WARN, f"{detail}; not a git repository, so there is no history to recover from")
    return Finding("vault", OK, detail)


def _index(vault: Path) -> Finding:
    """Whether the generated files match what regenerating them right now would produce.

    Deliberately a content comparison and not an mtime one. A rebase, a checkout or a
    fresh clone rewrites every file's mtime without changing a byte, so an mtime check
    reports the whole vault as stale after each of them — and a check that cries wolf
    is one nobody reads. Content is the only signal that means what it says.
    """
    generated = [vault / name for name in (schema.INDEX_FILE, schema.BACKLINKS_FILE)]
    missing = [path.name for path in generated if not path.exists()]
    if missing:
        return Finding("index", WARN, f"{', '.join(missing)} absent; run `kb index`")
    articles, _ = schema.load_vault(vault)
    articles.sort(key=lambda article: article.slug)
    expected = {schema.INDEX_FILE: render_index(articles), schema.BACKLINKS_FILE: render_backlinks(articles)}
    drifted = [path.name for path in generated if path.read_text(encoding="utf-8") != expected[path.name]]
    if drifted:
        return Finding("index", WARN, f"{' and '.join(drifted)} out of date; run `kb index`")
    return Finding("index", OK, str(vault / schema.INDEX_FILE))


def _lint(vault: Path) -> Finding:
    findings = check(vault)
    errors = sum(1 for finding in findings if finding.severity == ERROR)
    warnings = len(findings) - errors
    if errors:
        return Finding("lint", CRIT, f"{errors} error(s), {warnings} warning(s); run `kb lint`")
    if warnings:
        return Finding("lint", WARN, f"{warnings} warning(s); run `kb lint`")
    return Finding("lint", OK, "no findings")


def _repo_root() -> Finding:
    """Where `repos:` names are resolved to checkouts. Nothing can be checked against code without it."""
    root = config.load_config().repo_root
    if not root.is_dir():
        return Finding("repo-root", WARN, f"{root} does not exist; nothing can be checked against its repos")
    count = sum(1 for child in root.iterdir() if (child / ".git").exists())
    return Finding("repo-root", OK, f"{root} ({count} repo(s))")


def _schema() -> Finding:
    path = config.schema_path()
    if not path.is_file():
        return Finding("schema", CRIT, f"SCHEMA.md is missing from the installed package (looked at {path})")
    return Finding("schema", OK, str(path))


def _skill_link() -> Finding:
    """Every shipped skill, since a half-installed set is the confusing case."""
    missing: list[str] = []
    wrong: list[str] = []
    for name in config.SKILL_NAMES:
        link, source = config.skill_link(name), config.skill_source(name)
        if not link.exists() and not link.is_symlink():
            missing.append(name)
        elif not link.is_symlink() or link.resolve() != source.resolve():
            wrong.append(name)
    if wrong:
        return Finding("skill-links", CRIT, f"not pointing at this checkout: {', '.join(wrong)}")
    if missing:
        return Finding("skill-links", WARN, f"absent: {', '.join(missing)}; run `kb skill install`")
    return Finding("skill-links", OK, f"{len(config.SKILL_NAMES)} skill(s) linked into {config.CLAUDE_SKILLS_DIR}")


def _worst(findings: list[Finding]) -> str:
    for status in (CRIT, WARN, SKIPPED):
        if any(finding.status == status for finding in findings):
            return status
    return OK
