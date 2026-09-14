"""`kb lint` — the cheap pass: everything checkable without reading the prose.

Every rule here is mechanical, which is why it is free enough to run on every capture
and in a pre-commit hook. A broken link should surface the moment it is created, not six
months later.

**Lint never fixes anything.** It reports, and exits 1 when it found an error, so a hook
can refuse the commit without the tool having silently rewritten the article.

The expensive pass — does this runbook still match the code, do two articles contradict
each other — needs a model and is not implemented here.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from .. import config, schema
from ..errors import VaultNotFoundError, run
from ..output import JsonOption, console, emit_json

ERROR = "error"
WARN = "warn"

_STYLES = {ERROR: "red", WARN: "yellow"}

#: How old `last_updated` may get before the article is worth re-reading. Not a defect —
#: an article can be years old and perfectly true — so it reports as a warning.
DEFAULT_STALE_MONTHS = 6

#: Any path-shaped span inside backticks. Which of them are worth checking is decided by
#: `_is_local`, not by this pattern.
_CITED_PATH = re.compile(r"`(?P<path>(?:~|/)[^`\n]+)`")


@dataclass(frozen=True)
class Finding:
    """One rule, one place it fired, and what to do about it."""

    rule: str
    severity: str
    path: str
    line: int
    detail: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


def lint(
    as_json: JsonOption = False,
    stale_months: Annotated[
        int,
        typer.Option("--stale-months", help="Warn when last_updated is older than this many months."),
    ] = DEFAULT_STALE_MONTHS,
) -> None:
    """Check every article for broken links, dead pointers, missing fields, and staleness."""
    with run():
        vault = config.load_config().vault
        if not vault.is_dir():
            raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
        findings = check(vault, stale_months=stale_months)
        errors = [finding for finding in findings if finding.severity == ERROR]
        if as_json:
            emit_json(
                {
                    "findings": [asdict(finding) for finding in findings],
                    "errors": len(errors),
                    "warnings": len(findings) - len(errors),
                }
            )
        else:
            _render(findings, len(errors), vault)
        if errors:
            raise typer.Exit(1)


def _render(findings: list[Finding], errors: int, vault: Path) -> None:
    """One line per finding, in `file:line: severity: rule: detail` form.

    Deliberately not a table: a table folds a long path across three rows at terminal
    width, and a folded `path:line` is no longer something a terminal will open. The path
    is absolute for the same reason — a relative one is not resolvable from wherever the
    shell happens to be, so the terminal guesses it is a URL and opens a browser.
    """
    if not findings:
        console.print("[green]Clean.[/green] No findings.")
        return
    for finding in findings:
        style = _STYLES[finding.severity]
        where = f"{vault / finding.path}" + (f":{finding.line}" if finding.line else "")
        console.print(
            f"[cyan]{where}[/cyan]: [{style}]{finding.severity}[/{style}]: "
            f"[dim]{finding.rule}[/dim]: {finding.detail}",
            highlight=False,
        )
    console.print(f"\n{errors} error(s), {len(findings) - errors} warning(s).")


def check(
    vault: Path,
    stale_months: int = DEFAULT_STALE_MONTHS,
    today: date | None = None,
    home: Path | None = None,
) -> list[Finding]:
    """Run every cheap rule over the vault and return the findings, sorted by location."""
    today = today or date.today()
    home = home or Path.home()
    articles, failures = schema.load_vault(vault)
    findings = [
        Finding("frontmatter-unreadable", ERROR, _relative(path, vault), 1, reason) for path, reason in failures
    ]
    known = {article.slug for article in articles}
    for article in articles:
        findings += _frontmatter(article, vault)
        findings += _reference(article, vault)
        findings += _links(article, vault, known)
        findings += _cited_paths(article, vault, home)
        findings += _placement(article, vault)
        findings += _staleness(article, vault, stale_months, today)
    findings += _duplicate_titles(articles, vault)
    findings += _orphans(articles, vault)
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.rule))


def _relative(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def _frontmatter(article: schema.Article, vault: Path) -> list[Finding]:
    where = _relative(article.path, vault)
    findings: list[Finding] = []
    for name in schema.REQUIRED_FIELDS:
        value = article.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            findings.append(Finding("frontmatter-missing-field", ERROR, where, 1, f"missing required field {name}"))
    if article.type and article.type not in schema.TYPES:
        allowed = ", ".join(sorted(schema.TYPES))
        findings.append(
            Finding("frontmatter-invalid-type", ERROR, where, 1, f"type: {article.type} is not one of {allowed}")
        )
    if article.status and article.status not in schema.STATUSES:
        allowed = ", ".join(sorted(schema.STATUSES))
        findings.append(
            Finding("frontmatter-invalid-status", ERROR, where, 1, f"status: {article.status} is not {allowed}")
        )
    for name in schema.LIST_FIELDS:
        value = article.get(name)
        if value is not None and not isinstance(value, list):
            findings.append(Finding("frontmatter-invalid-list", ERROR, where, 1, f"{name}: must be a list"))
    created, updated = article.date_field("created"), article.date_field("last_updated")
    for name, parsed in (("created", created), ("last_updated", updated)):
        if article.get(name) is not None and parsed is None:
            findings.append(
                Finding("frontmatter-invalid-date", ERROR, where, 1, f"{name}: {article.get(name)!r} is not YYYY-MM-DD")
            )
    if created and updated and updated < created:
        findings.append(
            Finding("frontmatter-date-order", ERROR, where, 1, f"last_updated {updated} is before created {created}")
        )
    return findings


def _reference(article: schema.Article, vault: Path) -> list[Finding]:
    """A `reference/` article's whole job is its `path:`. A dead one points at nothing."""
    if article.type != "reference":
        return []
    where = _relative(article.path, vault)
    raw = article.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return [Finding("reference-missing-path", ERROR, where, 1, "a reference article needs a path: field")]
    target = Path(raw.strip()).expanduser()
    if not target.is_absolute():
        target = (vault / target).resolve()
    if not target.exists():
        return [Finding("reference-dead-path", ERROR, where, 1, f"path: {raw} does not exist")]
    return []


def _links(article: schema.Article, vault: Path, known: set[str]) -> list[Finding]:
    where = _relative(article.path, vault)
    findings: list[Finding] = []
    for link in article.links():
        line = link.line or 1
        if link.is_bare:
            findings.append(
                Finding(
                    "link-bare-title",
                    ERROR,
                    where,
                    line,
                    f"{link.raw} resolves by filename and matches nothing; use [[path/slug|{link.target}]]",
                )
            )
            continue
        if link.in_table_row and not link.escaped:
            findings.append(
                Finding(
                    "link-unescaped-pipe",
                    ERROR,
                    where,
                    line,
                    f"{link.raw} splits across two cells in a table row; escape the pipe as \\|",
                )
            )
        target = link.target.split("#")[0].removesuffix(".md")
        if target and target not in known and not (vault / f"{target}.md").exists():
            findings.append(Finding("link-broken", ERROR, where, line, f"{link.raw} points at no such article"))
    return findings


def _is_local(cited: str, home: Path) -> bool:
    """Whether a path-shaped string could refer to a file on this machine.

    Deliberately narrow. Articles are full of HTTP endpoints (`/permits/rates`), slash
    commands (`/gaps-review`) and in-container paths (`/proc/1/root/tmp/`) — none exist
    here, none are defects, and checking them produced sixteen findings and zero real
    ones. A check that cries wolf is one nobody reads, so only home-rooted paths qualify.
    """
    if cited.startswith("~/"):
        return True
    return Path(cited).is_relative_to(home)


def _cited_paths(article: schema.Article, vault: Path, home: Path) -> list[Finding]:
    """Files the article points at by path, that are no longer there.

    The cheapest possible evidence that an article has drifted from what it describes,
    and the only such check that needs neither a model nor the code checked out.
    """
    where = _relative(article.path, vault)
    findings: list[Finding] = []
    seen: set[str] = set()
    for number, line in enumerate(article.body.splitlines(), start=1):
        for match in _CITED_PATH.finditer(line):
            cited = match.group("path").rstrip(".,;:)")
            if cited in seen or not _is_local(cited, home) or Path(cited).expanduser().exists():
                continue
            seen.add(cited)
            findings.append(
                Finding("cited-path-missing", WARN, where, number + article.body_offset, f"{cited} no longer exists")
            )
    return findings


def _placement(article: schema.Article, vault: Path) -> list[Finding]:
    where = _relative(article.path, vault)
    findings: list[Finding] = []
    if article.directory not in schema.DIRECTORIES:
        findings.append(
            Finding("unknown-directory", WARN, where, 1, f"{article.directory}/ is not a directory SCHEMA.md defines")
        )
    expected = schema.TYPE_DIRECTORY.get(article.type)
    if expected and article.directory in schema.DIRECTORIES and expected != article.directory:
        findings.append(
            Finding(
                "type-directory-mismatch",
                WARN,
                where,
                1,
                f"type: {article.type} normally lives in {expected}/, not {article.directory}/",
            )
        )
    return findings


def _staleness(article: schema.Article, vault: Path, stale_months: int, today: date) -> list[Finding]:
    """An `active` article is expected to change constantly, so age says nothing about it."""
    if article.is_active:
        return []
    updated = article.date_field("last_updated")
    if updated is None:
        return []
    months = (today.year - updated.year) * 12 + today.month - updated.month
    if months < stale_months:
        return []
    repos = article.list_field("repos")
    hint = f"check it against {', '.join(repos)}" if repos else "it carries no repos:, so nothing can auto-check it"
    return [
        Finding(
            "stale",
            WARN,
            _relative(article.path, vault),
            1,
            f"last_updated {updated} is {months} months old; {hint}",
        )
    ]


def _duplicate_titles(articles: list[schema.Article], vault: Path) -> list[Finding]:
    """Two articles with one title is the shape a missed update-vs-create decision leaves."""
    by_title: dict[str, list[schema.Article]] = {}
    for article in articles:
        if article.title:
            by_title.setdefault(article.title.strip().casefold(), []).append(article)
    findings: list[Finding] = []
    for group in by_title.values():
        if len(group) < 2:
            continue
        slugs = ", ".join(article.slug for article in group)
        for article in group:
            findings.append(
                Finding("duplicate-title", ERROR, _relative(article.path, vault), 1, f"title shared with {slugs}")
            )
    return findings


def _orphans(articles: list[schema.Article], vault: Path) -> list[Finding]:
    """`_index.md` links to everything, so it is deliberately not counted as a source."""
    known = {article.slug for article in articles}
    linked: set[str] = set()
    for article in articles:
        for link in article.links():
            target = link.target.split("#")[0].removesuffix(".md")
            if target in known and target != article.slug:
                linked.add(target)
    return [
        Finding("orphan", WARN, _relative(article.path, vault), 1, "nothing links to this article")
        for article in articles
        if article.slug not in linked
    ]
