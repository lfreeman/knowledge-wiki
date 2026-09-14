"""Shared option shapes and rendering.

`--json` and the human table never share a stream: an agent parsing `--json` gets a
bare JSON document on stdout with no Rich markup to strip.
"""

import json
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()
stderr = Console(stderr=True)

JsonOption = Annotated[bool, typer.Option("--json", help="Emit JSON on stdout instead of a table.")]

DryRunOption = Annotated[
    bool,
    typer.Option("--dry-run/--no-dry-run", help="Show what would change without writing. On by default."),
]


def emit_json(payload: Any) -> None:
    """Write a JSON document to stdout, unformatted by Rich."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def table(*columns: str) -> Table:
    """A table with the CLI's standard column styling."""
    built = Table(show_header=True, header_style="bold")
    for column in columns:
        built.add_column(column)
    return built
