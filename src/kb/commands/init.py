"""`kb init` — create the vault directories and write the config file.

Deliberately narrow. It does not install the skill and does not register a scheduled
job: a setup command that quietly adds a background job is a surprising side effect, and
the thing it added is exactly the thing nobody notices has stopped running. Those are
separate, explicit commands.

It also does not copy SCHEMA.md into the vault. Two copies of the rules drift, and the
whole design is built against that.
"""

from pathlib import Path
from typing import Annotated

import typer

from .. import config, schema
from ..commands.index import rebuild
from ..errors import run
from ..output import JsonOption, console, emit_json


def init(
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Where the vault lives. Defaults to the configured or built-in path."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Create the vault directories and write ~/.config/kb/config.json."""
    with run():
        root = vault.expanduser() if vault else config.load_config().vault
        created = [name for name in _directories() if not (root / name).is_dir()]
        for name in _directories():
            (root / name).mkdir(parents=True, exist_ok=True)
        config_path = config.config_file()
        config.ensure_config_dir()
        settings = {"vault": str(root), "model": config.load_config().model}
        config_path.write_text(_json(settings), encoding="utf-8")
        result = rebuild(root)
        if as_json:
            emit_json(
                {
                    "vault": str(root),
                    "config": str(config_path),
                    "created": created,
                    "articles": result.articles,
                }
            )
            return
        made = f"  ([green]created {len(created)} director(ies)[/green])" if created else ""
        console.print(f"Vault: {root}{made}")
        console.print(f"Config: {config_path}")
        console.print(f"Indexed {result.articles} article(s).")
        console.print("\n[dim]Next: `kb skill install --no-dry-run` to make capture available to Claude Code.[/dim]")


def _directories() -> list[str]:
    return [*schema.DIRECTORIES, f"{schema.RAW_DIRECTORY}/entries"]


def _json(settings: dict[str, str]) -> str:
    import json

    return json.dumps(settings, indent=2, sort_keys=True) + "\n"
