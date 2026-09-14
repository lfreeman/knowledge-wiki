"""Entry point. Registers the subcommand groups and holds no logic of its own."""

from typing import Annotated

import typer

from . import __version__, config
from .commands import index as index_cmd
from .commands import lint as lint_cmd
from .commands import schema_cmd

EPILOG = (
    f"Config: {config.config_file()}    Vault: {config.load_config().vault}\n\n"
    "Overrides: KB_CONFIG_DIR, KB_VAULT, KB_MODEL (shell environment wins over config.json)."
)

app = typer.Typer(
    name="kb",
    help="Maintain a personal knowledge base of plain markdown.",
    epilog=EPILOG,
    add_completion=True,
)

# index, lint and schema are single commands, so they sit at the top level rather than behind
# a group that would read as `kb index index`.
app.command("index", rich_help_panel="Common")(index_cmd.index)
app.command("lint", rich_help_panel="Common")(lint_cmd.lint)
app.command("schema", rich_help_panel="Common")(schema_cmd.schema)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"kb {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version, is_eager=True, help="Print the version and exit."),
    ] = False,
) -> None:
    """A knowledge base that Claude writes and keeps tidy."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
