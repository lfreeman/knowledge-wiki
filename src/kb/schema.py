"""Parse and validate what SCHEMA.md describes.

The vocabulary here — directories, types, required fields, the wikilink form — is the
executable half of `SCHEMA.md`. When one changes the other has to, so they are edited
together and the tests assert they agree.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .errors import ArticleError

#: Directory -> what it holds. Also the order sections appear in `_index.md`.
DIRECTORIES: dict[str, str] = {
    "incidents": "what happened, why, and what to do about it",
    "systems": "how a thing works, usually across services",
    "runbooks": "operational procedures",
    "guides": "long-form technical references that live here",
    "learning": "active plans; live state, mutates every session",
    "research": "open investigations, reading notes, comparisons",
    "journal": "dated entries synthesized from a journal corpus",
    "reference": "pointers to documents that stay in their own repo",
}

#: Holds raw source entries, not articles. Never indexed, never linted as an article.
RAW_DIRECTORY = "raw"

TYPES: frozenset[str] = frozenset(
    {"system", "incident", "runbook", "guide", "learning", "reference", "research", "journal", "ticket", "concept"}
)

STATUSES: frozenset[str] = frozenset({"stable", "active"})

#: The natural home for each type. `ticket` and `concept` have none — they are filed
#: under the directory of whatever they describe.
TYPE_DIRECTORY: dict[str, str] = {
    "system": "systems",
    "incident": "incidents",
    "runbook": "runbooks",
    "guide": "guides",
    "learning": "learning",
    "reference": "reference",
    "research": "research",
    "journal": "journal",
}

REQUIRED_FIELDS: tuple[str, ...] = ("title", "type", "status", "created", "last_updated", "summary")

#: Fields that must be a list of strings when present.
LIST_FIELDS: tuple[str, ...] = ("tickets", "repos", "systems", "related", "sources")

INDEX_FILE = "_index.md"
BACKLINKS_FILE = "_backlinks.json"
ABSORB_LOG_FILE = "_absorb_log.json"
GENERATED_FILES: tuple[str, ...] = (INDEX_FILE, BACKLINKS_FILE, ABSORB_LOG_FILE)

#: `[[...]]` with no nested brackets. The inner text is split on the pipe afterwards,
#: because the escaped form `\|` has to be told apart from the bare one.
_WIKILINK = re.compile(r"\[\[(?P<inner>[^\[\]]+)\]\]")


@dataclass(frozen=True)
class WikiLink:
    """One `[[...]]` occurrence, with everything lint needs to judge it."""

    target: str
    alias: str | None
    raw: str
    line: int
    escaped: bool
    in_table_row: bool

    @property
    def is_bare(self) -> bool:
        """True when the link carries no path — `[[Display Title]]`, which resolves to nothing."""
        return self.alias is None


@dataclass(frozen=True)
class Article:
    """One markdown file under a vault directory, with its frontmatter parsed."""

    path: Path
    slug: str
    directory: str
    frontmatter: dict[str, Any]
    body: str
    body_offset: int = field(default=0, repr=False)

    def get(self, key: str) -> Any:
        return self.frontmatter.get(key)

    @property
    def title(self) -> str:
        value = self.get("title")
        return value if isinstance(value, str) else ""

    @property
    def type(self) -> str:
        value = self.get("type")
        return value if isinstance(value, str) else ""

    @property
    def status(self) -> str:
        value = self.get("status")
        return value if isinstance(value, str) else ""

    @property
    def summary(self) -> str:
        value = self.get("summary")
        return value if isinstance(value, str) else ""

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def list_field(self, key: str) -> list[str]:
        """A list-valued field as strings, or an empty list when absent or malformed."""
        value = self.get(key)
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def date_field(self, key: str) -> date | None:
        """A date-valued field, or None when absent or unparseable.

        PyYAML already turns a bare `YYYY-MM-DD` into a `date`; a quoted one stays a
        string and is parsed here so both spellings behave the same.
        """
        value = self.get(key)
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                return None
        return None

    def links(self) -> list[WikiLink]:
        """Every wikilink in the article: the `related:` field first, then the body."""
        found = [link for value in self.list_field("related") for link in wikilinks(value, line=0)]
        found.extend(wikilinks(self.body, line_offset=self.body_offset))
        return found


def wikilinks(text: str, line: int | None = None, line_offset: int = 0) -> list[WikiLink]:
    """Every `[[...]]` in `text`, with its line number and table context.

    `line` pins every result to one line number, for text that did not come from the
    body (a `related:` entry). `line_offset` shifts body line numbers so they point at
    the real position in the file.
    """
    results: list[WikiLink] = []
    for number, content in enumerate(text.splitlines(), start=1):
        in_table_row = content.lstrip().startswith("|")
        for match in _WIKILINK.finditer(content):
            inner = match.group("inner")
            if "\\|" in inner:
                target, _, alias = inner.partition("\\|")
                escaped = True
            elif "|" in inner:
                target, _, alias = inner.partition("|")
                escaped = False
            else:
                target, alias, escaped = inner, None, False
            results.append(
                WikiLink(
                    target=target.strip(),
                    alias=alias.strip() if alias is not None else None,
                    raw=match.group(0),
                    line=line if line is not None else number + line_offset,
                    escaped=escaped,
                    in_table_row=in_table_row,
                )
            )
    return results


def split_frontmatter(text: str) -> tuple[str, str, int]:
    """Split a document into its YAML frontmatter, its body, and the body's line offset.

    Raises `ArticleError` when the document does not open with a `---` fence.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ArticleError("no YAML frontmatter: the file does not start with ---")
    for number, content in enumerate(lines[1:], start=1):
        if content.strip() == "---":
            return "\n".join(lines[1:number]), "\n".join(lines[number + 1 :]), number + 1
    raise ArticleError("frontmatter is never closed: no second --- line")


def parse_article(path: Path, vault: Path) -> Article:
    """Read one article. Raises `ArticleError` if it cannot be read as one."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArticleError(f"{path}: {exc}") from exc
    raw_frontmatter, body, offset = split_frontmatter(text)
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise ArticleError(f"{path}: frontmatter is not valid YAML: {_yaml_reason(exc)}") from exc
    if not isinstance(loaded, dict):
        raise ArticleError(f"{path}: frontmatter must be a YAML mapping")
    relative = path.relative_to(vault)
    return Article(
        path=path,
        slug=relative.with_suffix("").as_posix(),
        directory=relative.parts[0] if len(relative.parts) > 1 else "",
        frontmatter=loaded,
        body=body,
        body_offset=offset,
    )


def _yaml_reason(exc: yaml.YAMLError) -> str:
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem and mark is not None:
        return f"{problem} (frontmatter line {mark.line + 1})"
    return str(exc).replace("\n", " ")


def article_paths(vault: Path) -> Iterator[Path]:
    """Every file in the vault that is meant to be an article.

    Skips generated files, the `raw/` entry store, dotted directories such as an
    editor's config, and anything at the vault root — an article always lives in a
    directory. Symlinks are followed, because an adopted document is often reachable
    only through one.
    """
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault)
        if len(relative.parts) < 2:
            continue
        if relative.parts[0] == RAW_DIRECTORY or any(part.startswith(".") for part in relative.parts):
            continue
        if path.name.startswith("_"):
            continue
        yield path


def load_vault(vault: Path) -> tuple[list[Article], list[tuple[Path, str]]]:
    """Read every article in the vault.

    Returns the articles that parsed and, separately, the ones that did not with the
    reason — so a single broken file reports as a finding instead of aborting the run.
    """
    articles: list[Article] = []
    failures: list[tuple[Path, str]] = []
    for path in article_paths(vault):
        try:
            articles.append(parse_article(path, vault))
        except ArticleError as exc:
            failures.append((path, str(exc).removeprefix(f"{path}: ")))
    return articles, failures
