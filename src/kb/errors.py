"""User-facing error types and the helper that renders them.

A `KbError` is a condition the user can act on: a missing vault, an article whose
frontmatter will not parse, a link that cannot be created safely. Anything else is a
bug and keeps its traceback.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import typer
from rich.console import Console

_stderr = Console(stderr=True)


class KbError(Exception):
    """Base for every condition the user is expected to resolve."""


class ConfigError(KbError):
    """The config file exists but cannot be used."""


class VaultNotFoundError(KbError):
    """The configured vault directory does not exist."""


class ArticleError(KbError):
    """An article on disk cannot be read as an article."""


class SkillInstallError(KbError):
    """The skill link cannot be created safely."""


@contextmanager
def run() -> Iterator[None]:
    """Render a `KbError` as a one-line `Error:` on stderr and exit 1.

    Any other exception propagates untouched, so a bug still produces a traceback.
    """
    try:
        yield
    except KbError as exc:
        _stderr.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
