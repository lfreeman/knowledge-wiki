"""`kb skill` — make the capture skill discoverable.

Claude Code finds skills by scanning ~/.claude/skills, so the CLI links the repo
directory into it rather than copying. The skill then versions with the CLI it calls,
and editing it in the repo takes effect immediately with no second copy to drift.
"""

import typer

from .. import config
from ..errors import SkillInstallError, run
from ..output import DryRunOption, JsonOption, console, emit_json

app = typer.Typer(help="Install the capture skill into Claude Code.", no_args_is_help=True)


@app.command()
def install(dry_run: DryRunOption = True) -> None:
    """Symlink the repo's skill directory into ~/.claude/skills."""
    with run():
        link = config.skill_link()
        source = config.skill_source()
        if not source.is_dir():
            raise SkillInstallError(f"no skill directory at {source}; install kb from a checkout")
        if link.is_symlink() and link.resolve() == source.resolve():
            console.print(f"Already installed: {link} -> {source}")
            return
        if link.exists() and not link.is_symlink():
            raise SkillInstallError(f"{link} is a real directory, not a link; move it aside first")
        if dry_run:
            action = "repoint" if link.is_symlink() else "create"
            console.print(f"Would {action} {link} -> {source}")
            console.print("Pass [bold]--no-dry-run[/bold] to do it.")
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(source, target_is_directory=True)
        console.print(f"Installed: {link} -> {source}")
        console.print("[dim]Start a new Claude Code session to pick it up.[/dim]")


@app.command()
def status(as_json: JsonOption = False) -> None:
    """Report whether the skill link exists and what it resolves to."""
    with run():
        link = config.skill_link()
        installed = link.is_symlink()
        target = str(link.resolve()) if installed else None
        if as_json:
            emit_json(
                {
                    "installed": installed,
                    "link": str(link),
                    "target": target,
                    "source": str(config.skill_source().resolve()),
                }
            )
            return
        if not installed:
            console.print(f"Not installed. Run [bold]kb skill install --no-dry-run[/bold] to link {link}.")
            return
        console.print(f"{link} -> {target}")
