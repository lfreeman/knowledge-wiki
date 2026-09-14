"""`kb adopt` — the mechanical half of the adoption procedure.

The split is deliberate and is the whole reason this command is three verbs rather than
one. Classification is judgment: is this document raw material, a finished document that
rightfully lives next to its code, a finished document with no home, or live state a
workflow rewrites every run? A script cannot answer that. So:

    kb adopt inspect   gathers the evidence — read-only, decides nothing
    kb adopt move      executes "it is homeless": move it in, fix its links
    kb adopt point     executes "it belongs where it is": write a stub at it

`inspect` exists because step 3 of the procedure is the one that is easy to skip and
expensive to skip: it fails silently, as a broken link in a repository nobody opens for
a month. Having a command do the grep makes skipping it the harder path.

Both writing verbs are dry-run by default.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from .. import config, schema
from ..errors import ArticleError, KbError, VaultNotFoundError, run
from ..output import DryRunOption, JsonOption, console, emit_json

app = typer.Typer(help="Bring an existing document into the vault, or point at it where it is.")

#: Directories a sweep should never descend into when looking for inbound references.
SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist",
     "build", "target", ".idea", ".gradle", ".terraform"}
)

#: Extensions worth scanning for a mention of a filename.
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".cfg", ".py",
                           ".sh", ".java", ".kt", ".ts", ".js", ".tsx", ".jsx", ".gradle", ".xml", ".properties"})

#: A markdown link: the target is group 2.
_MD_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?P<title>\s+\"[^\"]*\")?\)")

#: Link targets that are already unambiguous from anywhere.
_ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|/|~|#)")

_MAX_INBOUND = 200


@dataclass(frozen=True)
class Reference:
    """One place a path was named."""

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Inspection:
    """Everything steps 1 and 3 of the procedure ask for, and nothing decided."""

    path: str
    exists: bool
    lines: int
    heading: str | None
    has_frontmatter: bool
    repo: str | None
    repo_name: str | None
    names_own_repo: bool
    listed_in_repo_docs: list[str]
    outbound_relative: list[Reference]
    inbound: list[Reference]


@app.command()
def inspect(
    path: Annotated[Path, typer.Argument(help="The document to look at.")],
    search: Annotated[
        list[Path] | None,
        typer.Option("--search", help="Extra directory to scan for inbound references. Repeatable."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Gather the evidence for classifying a document. Reads only; changes nothing."""
    with run():
        result = examine(path.expanduser(), extra_roots=[root.expanduser() for root in (search or [])])
        if as_json:
            emit_json(asdict(result))
            return
        _render_inspection(result)


def examine(path: Path, extra_roots: list[Path] | None = None) -> Inspection:
    """Read a document and everything around it that bears on where it belongs."""
    if not path.is_file():
        raise KbError(f"{path} is not a file")
    text = path.read_text(encoding="utf-8", errors="replace")
    repo = _repo_root(path)
    repo_name = repo.name if repo else None
    roots = [root for root in [repo, *(extra_roots or [])] if root is not None]
    return Inspection(
        path=str(path),
        exists=True,
        lines=len(text.splitlines()),
        heading=_first_heading(text),
        has_frontmatter=text.startswith("---"),
        repo=str(repo) if repo else None,
        repo_name=repo_name,
        names_own_repo=repo_name is not None and repo_name in text,
        listed_in_repo_docs=_listed_in_repo_docs(path, repo),
        outbound_relative=_outbound(path, text),
        inbound=_inbound(path, roots),
    )


def _repo_root(path: Path) -> Path | None:
    """The nearest enclosing git repository, which is the unit 'its own repo' means."""
    for candidate in path.resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return None


def _listed_in_repo_docs(path: Path, repo: Path | None) -> list[str]:
    """Whether the repo's own guidance files name this document.

    A repo that lists a document as project documentation is asserting the document
    belongs to it. A repo that never mentions it is a strong signal the document is
    only sitting there because someone needed a folder.
    """
    if repo is None:
        return []
    found: list[str] = []
    for name in ("CLAUDE.md", "AGENTS.md", "README.md", "docs/README.md"):
        candidate = repo / name
        if candidate.is_file() and path.name in candidate.read_text(encoding="utf-8", errors="replace"):
            found.append(name)
    return found


def _outbound(path: Path, text: str) -> list[Reference]:
    """Relative markdown links that resolve to a real file next to this document.

    Only links that actually resolve are reported. A link whose target does not exist
    was never a path into this repository, and rewriting it would be vandalism.
    """
    found: list[Reference] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _MD_LINK.finditer(line):
            target = match.group("target")
            if _ABSOLUTE.match(target):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            if resolved.exists():
                found.append(Reference(path=target, line=number, text=str(resolved)))
    return found


def _inbound(path: Path, roots: list[Path]) -> list[Reference]:
    """Every line under `roots` that names this document's filename.

    The document itself is excluded, and so is anything under a build or vendor
    directory — those are copies, not references.
    """
    needle = path.name
    resolved_self = path.resolve()
    found: list[Reference] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in _text_files(root):
            if candidate in seen or candidate == resolved_self:
                continue
            seen.add(candidate)
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle not in content:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if needle in line:
                    found.append(Reference(path=str(candidate), line=number, text=line.strip()[:160]))
                    if len(found) >= _MAX_INBOUND:
                        return found
    return found


def _text_files(root: Path) -> list[Path]:
    results: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRECTORIES and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix.lower() in TEXT_SUFFIXES:
                results.append(entry.resolve())
    return sorted(results)


def _render_inspection(result: Inspection) -> None:
    console.print(f"[bold]{result.path}[/bold]  ({result.lines} lines)")
    if result.heading:
        console.print(f"  heading: {result.heading}")
    console.print(f"  repo: {result.repo or '[dim]not inside a git repository[/dim]'}")
    if result.repo_name:
        verdict = "names its own repo" if result.names_own_repo else "[yellow]never names its own repo[/yellow]"
        console.print(f"  {verdict} ({result.repo_name})")
    listed = ", ".join(result.listed_in_repo_docs) or "[yellow]not listed in the repo's own docs[/yellow]"
    console.print(f"  listed in: {listed}")
    console.print(f"  outbound relative links: {len(result.outbound_relative)}")
    for reference in result.outbound_relative:
        console.print(f"    [cyan]{result.path}:{reference.line}[/cyan]  {reference.path}")
    console.print(f"  inbound references: {len(result.inbound)}")
    for reference in result.inbound:
        console.print(f"    [cyan]{reference.path}:{reference.line}[/cyan]  {reference.text}")
    console.print(
        "\n[dim]Nothing was decided or changed. Classify per `kb schema` §6, then run "
        "`kb adopt move` or `kb adopt point`.[/dim]"
    )


class SourceAction(StrEnum):
    """What happens to the original file once its content is in the vault."""

    REMOVE = "remove"
    SYMLINK = "symlink"
    KEEP = "keep"


@app.command()
def move(
    path: Annotated[Path, typer.Argument(help="The homeless document to bring in.")],
    to: Annotated[str, typer.Option("--to", help="Vault directory to move it into, e.g. runbooks.")],
    title: Annotated[str | None, typer.Option("--title", help="Defaults to the document's first heading.")] = None,
    summary: Annotated[str, typer.Option("--summary", help="One or two sentences for the index.")] = "",
    kind: Annotated[str | None, typer.Option("--type", help="Defaults to the type that lives in --to.")] = None,
    status: Annotated[str, typer.Option("--status", help="stable, or active for live state.")] = "stable",
    slug: Annotated[str | None, typer.Option("--slug", help="Defaults to a slug of the filename.")] = None,
    created: Annotated[str | None, typer.Option("--created", help="Defaults to the file's modification date.")] = None,
    repos: Annotated[list[str] | None, typer.Option("--repo", help="Repeatable.")] = None,
    systems: Annotated[list[str] | None, typer.Option("--system", help="Repeatable.")] = None,
    tickets: Annotated[list[str] | None, typer.Option("--ticket", help="Repeatable.")] = None,
    related: Annotated[list[str] | None, typer.Option("--related", help="[[path/slug|Title]]. Repeatable.")] = None,
    note: Annotated[str | None, typer.Option("--note", help="Free text about the placement.")] = None,
    source: Annotated[
        SourceAction,
        typer.Option("--source", help="What happens to the original: remove it, replace it with a symlink, or keep."),
    ] = SourceAction.REMOVE,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Move a homeless document into the vault, with frontmatter and absolutised links."""
    with run():
        source_path = path.expanduser()
        if not source_path.is_file():
            raise KbError(f"{source_path} is not a file")
        if to not in schema.DIRECTORIES:
            raise KbError(f"--to {to} is not a vault directory; one of: {', '.join(schema.DIRECTORIES)}")
        vault = _vault()
        existing, body = _split(source_path)
        heading = _first_heading(body)
        resolved_title = title or existing.get("title") or heading or source_path.stem
        rewritten, rewrites = _absolutise(source_path, body)
        target = vault / to / f"{slug or schema.slugify(source_path.stem)}.md"
        fields: dict[str, Any] = dict(existing)
        fields.update(
            {
                "title": resolved_title,
                "type": kind or _type_for(to) or existing.get("type") or "concept",
                "status": status,
                "created": created or existing.get("created") or _mtime_date(source_path),
                "last_updated": date.today().isoformat(),
                "summary": summary or existing.get("summary") or "",
            }
        )
        _merge_lists(fields, repos=repos, systems=systems, tickets=tickets, related=related)
        if note:
            fields["note"] = note
        text = schema.render_article(fields, rewritten)
        plan = {
            "action": "move",
            "source": str(source_path),
            "target": str(target),
            "source_action": source.value,
            "links_absolutised": [asdict(reference) for reference in rewrites],
            "dry_run": dry_run,
        }
        if not dry_run:
            _guard(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            if source is SourceAction.SYMLINK:
                source_path.unlink()
                source_path.symlink_to(target)
            elif source is SourceAction.REMOVE:
                source_path.unlink()
        _report(plan, text, as_json, dry_run)


@app.command()
def point(
    path: Annotated[Path, typer.Argument(help="The document that rightfully stays where it is.")],
    title: Annotated[str | None, typer.Option("--title", help="Defaults to the document's first heading.")] = None,
    summary: Annotated[str, typer.Option("--summary", help="What it covers. Does not restate it.")] = "",
    slug: Annotated[str | None, typer.Option("--slug", help="Defaults to a slug of the filename.")] = None,
    repos: Annotated[list[str] | None, typer.Option("--repo", help="Repeatable.")] = None,
    systems: Annotated[list[str] | None, typer.Option("--system", help="Repeatable.")] = None,
    tickets: Annotated[list[str] | None, typer.Option("--ticket", help="Repeatable.")] = None,
    related: Annotated[list[str] | None, typer.Option("--related", help="[[path/slug|Title]]. Repeatable.")] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Write a reference/ stub pointing at a document. Moves nothing, restates nothing."""
    with run():
        source_path = path.expanduser()
        if not source_path.exists():
            raise KbError(f"{source_path} does not exist")
        vault = _vault()
        heading = _first_heading(_split(source_path)[1]) if source_path.is_file() else None
        resolved_title = title or heading or source_path.stem
        target = vault / "reference" / f"{slug or schema.slugify(source_path.stem)}.md"
        fields: dict[str, Any] = {
            "title": resolved_title,
            "type": "reference",
            "status": "stable",
            "created": date.today().isoformat(),
            "last_updated": date.today().isoformat(),
            "summary": summary,
            "path": str(source_path.resolve()),
        }
        _merge_lists(fields, repos=repos, systems=systems, tickets=tickets, related=related)
        text = schema.render_article(fields, _stub(resolved_title, source_path))
        plan = {
            "action": "point",
            "source": str(source_path),
            "target": str(target),
            "source_action": SourceAction.KEEP.value,
            "links_absolutised": [],
            "dry_run": dry_run,
        }
        if not dry_run:
            _guard(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        _report(plan, text, as_json, dry_run)


def _stub(title: str, source: Path) -> str:
    return (
        f"# {title}\n\n"
        f"The document itself lives at `{source.resolve()}`.\n\n"
        "**Read it there.** This article deliberately does not restate its content, which is "
        "what keeps the two from drifting apart: there is only ever one copy to be wrong.\n"
    )


def _vault() -> Path:
    vault = config.load_config().vault
    if not vault.is_dir():
        raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
    return vault


def _guard(target: Path) -> None:
    if target.exists():
        raise KbError(f"{target} already exists; pass a different --slug or update that article instead")


def _split(path: Path) -> tuple[dict[str, Any], str]:
    """Existing frontmatter, if any, and the body. A document without frontmatter is normal."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        parsed = schema.parse_article(path, path.parent)
    except ArticleError:
        return {}, text
    return dict(parsed.frontmatter), parsed.body


def _type_for(directory: str) -> str | None:
    for name, home in schema.TYPE_DIRECTORY.items():
        if home == directory:
            return name
    return None


def _mtime_date(path: Path) -> str:
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


def _merge_lists(fields: dict[str, Any], **provided: list[str] | None) -> None:
    """Provided values replace an existing list; an absent option leaves it alone."""
    for name, values in provided.items():
        if values:
            fields[name] = values


def _absolutise(source: Path, body: str) -> tuple[str, list[Reference]]:
    """Rewrite relative markdown links as absolute ones.

    A relative link is meaningless once the document lives somewhere else. An absolute
    path reads correctly from the vault *and* from the original location, so this is a
    pure win. Only links that resolve to a real file are touched.
    """
    rewrites: list[Reference] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):

        def replace(match: re.Match[str], number: int = index + 1) -> str:
            target = match.group("target")
            if _ABSOLUTE.match(target):
                return match.group(0)
            anchor = ""
            bare = target
            if "#" in target:
                bare, _, fragment = target.partition("#")
                anchor = f"#{fragment}"
            resolved = (source.parent / bare).resolve()
            if not resolved.exists():
                return match.group(0)
            rewrites.append(Reference(path=target, line=number, text=str(resolved)))
            return f"[{match.group('text')}]({resolved}{anchor}{match.group('title') or ''})"

        lines[index] = _MD_LINK.sub(replace, line)
    return "\n".join(lines), rewrites


def _report(plan: dict[str, Any], text: str, as_json: bool, dry_run: bool) -> None:
    if as_json:
        emit_json({**plan, "article": text})
        return
    verb = "Would write" if dry_run else "Wrote"
    console.print(f"{verb} [bold]{plan['target']}[/bold]")
    if plan["links_absolutised"]:
        console.print(f"  absolutised {len(plan['links_absolutised'])} relative link(s):")
        for reference in plan["links_absolutised"]:
            console.print(f"    [cyan]{plan['source']}:{reference['line']}[/cyan]  {reference['path']}")
    if plan["source_action"] == SourceAction.SYMLINK.value:
        console.print(f"  {'would replace' if dry_run else 'replaced'} {plan['source']} with a symlink to it")
        console.print("  [dim]note: git stores a symlink as a path string, not content[/dim]")
    elif plan["source_action"] == SourceAction.REMOVE.value:
        console.print(f"  [yellow]{'would remove' if dry_run else 'removed'}[/yellow] {plan['source']}")
    if dry_run:
        console.print("\n[dim]--- article that would be written ---[/dim]")
        console.print(text, highlight=False, markup=False)
        console.print("[bold]Pass --no-dry-run to do it.[/bold]")
    else:
        console.print("\n[dim]Next: `kb index`, then `kb lint`.[/dim]")
