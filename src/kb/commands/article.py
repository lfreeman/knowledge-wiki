"""`kb article` — create an article, or bump the date on one.

Both commands exist for the same reason: they are the parts of writing an article that
are mechanical, and a model doing them by hand gets them subtly wrong. Frontmatter is
YAML, so a summary containing a colon has to be quoted and a title containing a pipe has
to survive a table cell; and `last_updated` is the field the whole staleness story rests
on, which makes it exactly the field that gets forgotten.

The prose is not mechanical, and neither command writes any. Pass the body in with
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

app = typer.Typer(help="Create an article, or bump last_updated on one.", no_args_is_help=True)


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
            "created": created or date.today().isoformat(),
            "last_updated": date.today().isoformat(),
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
def touch(
    slugs: Annotated[list[str], typer.Argument(help="Vault-relative slugs to bump.")],
    on: Annotated[str | None, typer.Option("--on", help="Date to set. Defaults to today.")] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Set last_updated on articles you just edited."""
    with run():
        vault = _vault()
        stamp = on or date.today().isoformat()
        changed: list[dict[str, str]] = []
        for slug in slugs:
            target = _target(vault, slug)
            if not target.is_file():
                raise KbError(f"no article at {target}")
            text = target.read_text(encoding="utf-8")
            try:
                front, body, _ = schema.split_frontmatter(text)
            except ArticleError as exc:
                raise KbError(f"{target}: {exc}") from exc
            fields = yaml.safe_load(front) or {}
            if not isinstance(fields, dict):
                raise KbError(f"{target}: frontmatter must be a YAML mapping")
            was = str(fields.get("last_updated", ""))
            fields["last_updated"] = stamp
            if not dry_run:
                target.write_text(schema.render_article(fields, body), encoding="utf-8")
            changed.append({"slug": slug, "from": was, "to": stamp})
        if as_json:
            emit_json({"changed": changed, "dry_run": dry_run})
            return
        for entry in changed:
            arrow = f"{entry['from'] or '(none)'} -> {entry['to']}"
            console.print(f"{'Would bump' if dry_run else 'Bumped'} [bold]{entry['slug']}[/bold]  {arrow}")
        if dry_run:
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


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
