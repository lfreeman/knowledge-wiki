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

import json
import re
import subprocess
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

#: A relative path written in backticks rather than as a markdown link, e.g. `../notes.md`.
_BACKTICKED_PATH = re.compile(r"`(?P<path>\.{0,2}/[^`\s]+|[\w.-]+/[^`\s]+\.\w{1,5})`")

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
    outbound_broken: list[Reference]
    inbound: list[Reference]
    searched: list[str]
    ambiguous_name: bool
    tracked_by_git: bool | None


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
    # The enclosing repo alone is not enough. A document is most often referenced from a
    # *different* repo, which is exactly the reference that breaks silently on a move —
    # searching only the enclosing repo once missed both real inbound references.
    roots = _dedupe([root for root in [repo, config.load_config().repo_root, *(extra_roots or [])] if root])
    inbound = _inbound(path, roots)
    resolves, broken = _outbound(path, text)
    return Inspection(
        path=str(path),
        exists=True,
        lines=len(text.splitlines()),
        heading=_first_heading(text),
        has_frontmatter=text.startswith("---"),
        repo=str(repo) if repo else None,
        repo_name=repo_name,
        names_own_repo=repo_name is not None and repo_name in _prose(text),
        listed_in_repo_docs=_listed_in_repo_docs(path, repo),
        outbound_relative=resolves,
        outbound_broken=broken,
        inbound=inbound,
        searched=[str(root) for root in roots],
        ambiguous_name=_is_common_name(path, roots),
        tracked_by_git=_tracked_by_git(path, repo),
    )


def _prose(text: str) -> str:
    """The document with code stripped out.

    `names_own_repo` asks whether the document *says* it is about the repo it sits in. A
    dependency coordinate in an XML sample is not that claim — one real document's only
    mention of its repo was `<artifactId>some-service-integration</artifactId>` inside a
    fenced block, and the heuristic called it owned when it was not.
    """
    kept: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or line.startswith("    ") or line.startswith("\t"):
            continue
        kept.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(kept)


def _tracked_by_git(path: Path, repo: Path | None) -> bool | None:
    """Whether the enclosing repository tracks this file. None when there is no repository.

    The strongest mechanical signal there is. A repository that does not track a document
    is not claiming it — and an untracked document has no history and no backup, which
    makes moving it into the vault a rescue rather than a reorganisation.
    """
    if repo is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", str(path.resolve())],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.returncode == 0


def _dedupe(roots: list[Path]) -> list[Path]:
    """Keep only the broadest roots, so no directory is scanned twice.

    Order does not matter: the enclosing repo usually sits *inside* the configured repo
    root, so a first-wins rule would keep both and walk the repo twice.
    """
    resolved = list(dict.fromkeys(root.expanduser() for root in roots))
    return [
        root
        for root in resolved
        if not any(other != root and root.is_relative_to(other) for other in resolved)
    ]


def _is_common_name(path: Path, roots: list[Path]) -> bool:
    """Whether other files share this filename, which makes every inbound hit suspect.

    `architecture.md` and `README.md` live in half the repositories on a machine. A hit
    on the bare filename may point at a different file entirely, so the caller has to be
    told rather than left to assume.
    """
    resolved = path.resolve()
    seen = 0
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in _text_files(root):
            if candidate.name == path.name and candidate != resolved:
                seen += 1
                if seen:
                    return True
    return False


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


def _outbound(path: Path, text: str) -> tuple[list[Reference], list[Reference]]:
    """Relative paths this document points at, split into those that resolve and those that do not.

    Both halves matter and for opposite reasons. A link that resolves becomes meaningless
    once the document moves, so it has to be absolutised. A link that does *not* resolve
    is already broken — which is the thing step 3 exists to catch, and the thing an
    earlier version could never report, because it only ever listed the ones that worked.

    Backticked paths are included alongside markdown links. One real document referenced
    its companion as `../findings.md`, in backticks, and was therefore invisible.
    """
    resolves: list[Reference] = []
    broken: list[Reference] = []
    for number, line in enumerate(text.splitlines(), start=1):
        targets = [match.group("target") for match in _MD_LINK.finditer(line)]
        targets += [match.group("path") for match in _BACKTICKED_PATH.finditer(line)]
        for target in targets:
            if _ABSOLUTE.match(target):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            reference = Reference(path=target, line=number, text=str(resolved))
            (resolves if resolved.exists() else broken).append(reference)
    return resolves, broken


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
    if result.repo:
        listed = ", ".join(result.listed_in_repo_docs) or "[yellow]not listed in the repo's own docs[/yellow]"
        console.print(f"  listed in: {listed}")
    if result.tracked_by_git is False:
        console.print(
            "  [yellow]not tracked by git[/yellow] — the repo is not claiming it, and it has "
            "no history and no backup"
        )
    elif result.tracked_by_git:
        console.print("  tracked by git")
    console.print(f"  outbound relative links: {len(result.outbound_relative)} resolving")
    for reference in result.outbound_relative:
        console.print(f"    [cyan]{result.path}:{reference.line}[/cyan]  {reference.path}")
    if result.outbound_broken:
        console.print(f"  [yellow]{len(result.outbound_broken)} broken relative reference(s)[/yellow]")
        for reference in result.outbound_broken:
            console.print(f"    [cyan]{result.path}:{reference.line}[/cyan]  [yellow]{reference.path}[/yellow]")
    console.print(f"  searched: {', '.join(result.searched)}")
    console.print(f"  inbound references: {len(result.inbound)}")
    if result.ambiguous_name and result.inbound:
        console.print(
            f"    [yellow]note: other files are also named {Path(result.path).name}, "
            "so a hit may point at a different one[/yellow]"
        )
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
    path: Annotated[Path | None, typer.Argument(help="The homeless document to bring in.")] = None,
    to: Annotated[str, typer.Option("--to", help="Vault directory to move it into, e.g. runbooks.")] = "",
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
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="JSON array of moves. One object per document, same keys as the options."),
    ] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Move a homeless document into the vault, with frontmatter and absolutised links.

    A whole directory at once with `--from-file`, because ten options on one command line
    is error-prone for a single file and unbearable across a hundred.
    """
    with run():
        vault = _vault()
        if from_file is not None:
            if path is not None:
                raise KbError("pass either a path or --from-file, not both")
            specs = _read_specs(from_file.expanduser())
        else:
            if path is None:
                raise KbError("give a document to move, or pass --from-file")
            specs = [
                {
                    "path": str(path),
                    "to": to,
                    "title": title,
                    "summary": summary,
                    "type": kind,
                    "status": status,
                    "slug": slug,
                    "created": created,
                    "repos": repos,
                    "systems": systems,
                    "tickets": tickets,
                    "related": related,
                    "note": note,
                    "source": source.value,
                }
            ]
        plans = [_move_one(spec, vault, dry_run) for spec in specs]
        if as_json:
            emit_json({"moves": plans, "dry_run": dry_run})
            return
        for plan in plans:
            _report(plan, plan["article"], as_json=False, dry_run=dry_run, verbose=len(plans) == 1)
        if len(plans) > 1:
            console.print(f"\n{'Would move' if dry_run else 'Moved'} {len(plans)} document(s).")
            if dry_run:
                console.print("[bold]Pass --no-dry-run to do it.[/bold]")


def _read_specs(path: Path) -> list[dict[str, Any]]:
    """Parse a batch file: a JSON array of move descriptions."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KbError(f"{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KbError(f"{path} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise KbError(f"{path} must contain a JSON array of objects")
    if not loaded:
        raise KbError(f"{path} is empty")
    return loaded


def _move_one(spec: dict[str, Any], vault: Path, dry_run: bool) -> dict[str, Any]:
    """Plan and, unless this is a preview, perform one move."""
    raw_path = spec.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise KbError(f"every move needs a path; got {spec!r}")
    source_path = Path(raw_path).expanduser()
    to = str(spec.get("to") or "")
    title, summary = spec.get("title"), str(spec.get("summary") or "")
    kind, slug, created = spec.get("type"), spec.get("slug"), spec.get("created")
    status = str(spec.get("status") or "stable")
    note = spec.get("note")
    repos, systems = spec.get("repos"), spec.get("systems")
    tickets, related = spec.get("tickets"), spec.get("related")
    source = SourceAction(str(spec.get("source") or SourceAction.REMOVE.value))

    if not source_path.is_file():
        raise KbError(f"{source_path} is not a file")
    if to not in schema.DIRECTORIES:
        raise KbError(f"{source_path}: --to {to!r} is not a vault directory; one of: {', '.join(schema.DIRECTORIES)}")
    if source is not SourceAction.KEEP:
        _guard_editor(source_path)
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
            "created": _date(created) or existing.get("created") or _mtime_date(source_path),
            "last_updated": date.today(),
            "summary": summary or existing.get("summary") or "",
        }
    )
    _merge_lists(fields, repos=repos, systems=systems, tickets=tickets, related=related)
    if note:
        fields["note"] = note
    text = schema.render_article(fields, rewritten)
    if not dry_run:
        _guard(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if source is SourceAction.SYMLINK:
            source_path.unlink()
            source_path.symlink_to(target)
        elif source is SourceAction.REMOVE:
            source_path.unlink()
    return {
        "action": "move",
        "source": str(source_path),
        "target": str(target),
        "source_action": source.value,
        "links_absolutised": [asdict(reference) for reference in rewrites],
        "dry_run": dry_run,
        "article": text,
    }


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
            "created": date.today(),
            "last_updated": date.today(),
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


#: Swap files an editor leaves beside a file it currently has open.
_EDITOR_SWAP_SUFFIXES = (".swp", ".swo", ".swn")


def _guard_editor(source: Path) -> None:
    """Refuse to remove a file an editor appears to have open.

    A move deletes the original. If a buffer is still open on it, saving from that buffer
    afterwards writes a stale copy back to a path that no longer exists — and the vault
    copy, which is now the only one, never sees the change.
    """
    swaps = [
        candidate
        for suffix in _EDITOR_SWAP_SUFFIXES
        for candidate in (source.parent / f".{source.name}{suffix}", source.with_suffix(suffix))
        if candidate.exists()
    ]
    if swaps:
        names = ", ".join(str(swap) for swap in swaps)
        raise KbError(
            f"{source} looks open in an editor ({names}). Close it, or delete the stale swap file, "
            "then run this again — moving it now risks writing the old copy back from that buffer."
        )


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


def _mtime_date(path: Path) -> date:
    """A document's last-modified date, the best available stand-in for when it was written."""
    return date.fromtimestamp(path.stat().st_mtime)


def _date(value: str | None) -> date | None:
    """Parse a `YYYY-MM-DD` option. Returns a date, not a string, so it renders unquoted."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise KbError(f"{value!r} is not a YYYY-MM-DD date") from exc


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


def _report(plan: dict[str, Any], text: str, as_json: bool, dry_run: bool, verbose: bool = True) -> None:
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
    if dry_run and verbose:
        console.print("\n[dim]--- article that would be written ---[/dim]")
        console.print(text, highlight=False, markup=False)
        console.print("[bold]Pass --no-dry-run to do it.[/bold]")
    elif not dry_run and verbose:
        console.print("\n[dim]Next: `kb index`, then `kb lint`.[/dim]")
