"""`kb article` — create an article, relate two, or bump the date on one.

All three commands exist for the same reason: they are the parts of writing an article
that are mechanical, and a model doing them by hand gets them subtly wrong. Frontmatter
is YAML, so a summary containing a colon has to be quoted and a title containing a pipe
has to survive a table cell; `last_updated` is the field the whole staleness story rests
on, which makes it exactly the field that gets forgotten; and a `related:` link written
in only one direction leaves the other article reading as an orphan.

The prose is not mechanical, and none of these write any. Pass the body in with
`--body-file`, or leave it and edit the file afterwards.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from .. import config, schema
from ..errors import ArticleError, KbError, VaultNotFoundError, run
from ..output import DryRunOption, JsonOption, console, emit_json

app = typer.Typer(help="Create an article, relate two, or bump last_updated.", no_args_is_help=True)


@app.command()
def new(
    slug: Annotated[str, typer.Argument(help="Vault-relative slug, e.g. runbooks/restarting-the-thing.")],
    title: Annotated[str, typer.Option("--title", help="The human title.")],
    summary: Annotated[str, typer.Option("--summary", help="One or two sentences for the index.")],
    kind: Annotated[str | None, typer.Option("--type", help="Defaults to the directory's type.")] = None,
    status: Annotated[str, typer.Option("--status", help="stable, or active for live state.")] = "stable",
    body_file: Annotated[
        Path | None,
        typer.Option("--body-file", help="File holding the article body. Written verbatim under the frontmatter."),
    ] = None,
    created: Annotated[str | None, typer.Option("--created", help="Defaults to today.")] = None,
    repos: Annotated[list[str] | None, typer.Option("--repo", help="Repeatable. Lets lint auto-check it.")] = None,
    systems: Annotated[list[str] | None, typer.Option("--system", help="Repeatable.")] = None,
    tickets: Annotated[list[str] | None, typer.Option("--ticket", help="Repeatable.")] = None,
    related: Annotated[list[str] | None, typer.Option("--related", help="[[path/slug|Title]]. Repeatable.")] = None,
    sources: Annotated[list[str] | None, typer.Option("--source", help="Raw entry id. Repeatable.")] = None,
    path: Annotated[str | None, typer.Option("--path", help="Required for a reference article.")] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Write a new article with valid frontmatter."""
    with run():
        vault = _vault()
        target = _target(vault, slug)
        if target.exists():
            raise KbError(f"{target} already exists; edit it instead — see the update-vs-create rule in `kb schema`")
        directory = slug.split("/")[0]
        fields: dict[str, Any] = {
            "title": title,
            "type": kind or _type_for(directory) or "concept",
            "status": status,
            "created": _date(created),
            "last_updated": date.today(),
            "summary": summary,
            "tickets": tickets or None,
            "repos": repos or None,
            "systems": systems or None,
            "related": related if related is not None else [],
            "sources": sources or None,
            "path": path,
        }
        body = body_file.expanduser().read_text(encoding="utf-8") if body_file else f"# {title}\n"
        text = schema.render_article({k: v for k, v in fields.items() if v is not None}, body)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if as_json:
            emit_json({"slug": slug, "target": str(target), "dry_run": dry_run, "article": text})
            return
        console.print(f"{'Would write' if dry_run else 'Wrote'} [bold]{target}[/bold]")
        if dry_run:
            console.print("\n[dim]--- article that would be written ---[/dim]")
            console.print(text, highlight=False, markup=False)
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")
        else:
            console.print("[dim]Next: `kb index`, then `kb lint`.[/dim]")


@app.command()
def link(
    first: Annotated[str, typer.Argument(help="Vault-relative slug.")],
    second: Annotated[str, typer.Argument(help="The slug to link it to.")],
    one_way: Annotated[
        bool,
        typer.Option("--one-way", help="Only add the link to the first article. Rarely what you want."),
    ] = False,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Relate two articles, writing the link into both of their related: fields.

    Deciding that two articles belong together is judgment. Writing the second half of
    the pair is bookkeeping, and it is the half that gets forgotten — a one-way link
    leaves the other article looking like an orphan even though something points at it.
    """
    with run():
        vault = _vault()
        pairs = [(first, second)] if one_way else [(first, second), (second, first)]
        changed: list[dict[str, str]] = []
        for source, target in pairs:
            source_path, target_path = _target(vault, source), _target(vault, target)
            for path, slug in ((source_path, source), (target_path, target)):
                if not path.is_file():
                    raise KbError(f"no article at {path} (from slug {slug!r})")
            wikilink = f"[[{_slug(vault, target_path)}|{_title(target_path)}]]"
            fields, body = _fields(source_path)
            related = list(fields.get("related") or [])
            already = any(item.split("|")[0].strip("[ ") == _slug(vault, target_path) for item in related)
            if already:
                changed.append({"article": source, "link": wikilink, "action": "already present"})
                continue
            related.append(wikilink)
            fields["related"] = related
            fields["last_updated"] = date.today()
            if not dry_run:
                source_path.write_text(schema.render_article(fields, body), encoding="utf-8")
            changed.append({"article": source, "link": wikilink, "action": "added"})
        if as_json:
            emit_json({"changed": changed, "dry_run": dry_run})
            return
        for entry in changed:
            verb = "would add" if dry_run and entry["action"] == "added" else entry["action"]
            console.print(f"{entry['article']}: {verb} {entry['link']}", markup=False, highlight=False)
        if dry_run and any(entry["action"] == "added" for entry in changed):
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


@app.command()
def touch(
    slugs: Annotated[list[str], typer.Argument(help="Vault-relative slugs to bump.")],
    on: Annotated[str | None, typer.Option("--on", help="Date to set. Defaults to today.")] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Set last_updated on articles you just edited."""
    with run():
        vault = _vault()
        stamp = _date(on)
        changed: list[dict[str, str]] = []
        for slug in slugs:
            target = _target(vault, slug)
            if not target.is_file():
                raise KbError(f"no article at {target}")
            fields, body = _fields(target)
            was = str(fields.get("last_updated", ""))
            fields["last_updated"] = stamp
            if not dry_run:
                target.write_text(schema.render_article(fields, body), encoding="utf-8")
            changed.append({"slug": slug, "from": was, "to": stamp.isoformat()})
        if as_json:
            emit_json({"changed": changed, "dry_run": dry_run})
            return
        for entry in changed:
            arrow = f"{entry['from'] or '(none)'} -> {entry['to']}"
            console.print(f"{'Would bump' if dry_run else 'Bumped'} [bold]{entry['slug']}[/bold]  {arrow}")
        if dry_run:
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


def _fields(path: Path) -> tuple[dict[str, Any], str]:
    """An article's frontmatter as a mapping, plus its body."""
    try:
        front, body, _ = schema.split_frontmatter(path.read_text(encoding="utf-8"))
    except ArticleError as exc:
        raise KbError(f"{path}: {exc}") from exc
    loaded = yaml.safe_load(front) or {}
    if not isinstance(loaded, dict):
        raise KbError(f"{path}: frontmatter must be a YAML mapping")
    return loaded, body


def _title(path: Path) -> str:
    """An article's own title, so a link's alias never has to be typed twice."""
    fields, _ = _fields(path)
    title = fields.get("title")
    return str(title) if title else path.stem


def _slug(vault: Path, path: Path) -> str:
    return path.relative_to(vault).with_suffix("").as_posix()


def _date(value: str | None) -> date:
    """Parse a `YYYY-MM-DD` option, defaulting to today.

    Returns a `date` rather than a string so the renderer emits it bare. A string that
    looks like a date has to be quoted to survive the round trip, which would leave one
    date quoted and its neighbour not in the same frontmatter block.
    """
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise KbError(f"{value!r} is not a YYYY-MM-DD date") from exc


def _vault() -> Path:
    vault = config.load_config().vault
    if not vault.is_dir():
        raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
    return vault


def _target(vault: Path, slug: str) -> Path:
    cleaned = slug.strip("/").removesuffix(".md")
    if "/" not in cleaned or ".." in cleaned:
        raise KbError(f"{slug!r} is not a vault slug; it looks like directory/slug, e.g. runbooks/some-slug")
    return vault / f"{cleaned}.md"


def _type_for(directory: str) -> str | None:
    for name, home in schema.TYPE_DIRECTORY.items():
        if home == directory:
            return name
    return None
