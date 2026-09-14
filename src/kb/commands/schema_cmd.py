"""`kb schema` — print the rules both capture and ingest read.

SCHEMA.md ships inside the package and is deliberately never copied into a vault, so
this command is how a session gets at it without knowing where the package landed.
"""

from typing import Annotated

import typer

from .. import config
from ..errors import ConfigError, run
from ..output import console


def schema(
    path_only: Annotated[bool, typer.Option("--path", help="Print where SCHEMA.md lives and exit.")] = False,
) -> None:
    """Print SCHEMA.md, the rules this vault follows."""
    with run():
        path = config.schema_path()
        if not path.is_file():
            raise ConfigError(f"SCHEMA.md is missing from the installed package (looked at {path})")
        if path_only:
            console.print(str(path))
            return
        print(path.read_text(encoding="utf-8"), end="")
