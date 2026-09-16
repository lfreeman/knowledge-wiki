"""Entry point. Registers the subcommand groups and holds no logic of its own."""

from typing import Annotated

import typer

from . import __version__, config
from .commands import adopt, article, doctor, gap, schema_cmd, skill
from .commands import index as index_cmd
from .commands import init as init_cmd
from .commands import lint as lint_cmd
from .commands import search as search_cmd

EPILOG = (
    f"Config: {config.config_file()}    Vault: {config.load_config().vault}\n\n"
    "Overrides: KB_CONFIG_DIR, KB_VAULT, KB_REPO_ROOT, KB_MODEL (shell environment wins over config.json)."
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
app.command("search", rich_help_panel="Common")(search_cmd.search)
app.command("schema", rich_help_panel="Common")(schema_cmd.schema)
app.add_typer(article.app, name="article", rich_help_panel="Common")
app.add_typer(gap.app, name="gap", rich_help_panel="Common")
app.add_typer(adopt.app, name="adopt", rich_help_panel="Common")
app.add_typer(skill.app, name="skill", rich_help_panel="Setup")
app.command("init", rich_help_panel="Setup")(init_cmd.init)
app.command("doctor", rich_help_panel="Setup")(doctor.doctor)


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
