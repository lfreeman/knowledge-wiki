"""`kb skill` — make the skills discoverable.

Claude Code finds skills by scanning ~/.claude/skills, so the CLI links the repo
directories into it rather than copying. Each skill then versions with the CLI it calls,
and editing one in the repo takes effect immediately with no second copy to drift.
"""

import typer

from .. import config
from ..errors import SkillInstallError, run
from ..output import DryRunOption, JsonOption, console, emit_json

app = typer.Typer(help="Install the kb skills into Claude Code.", no_args_is_help=True)


@app.command()
def install(dry_run: DryRunOption = True) -> None:
    """Symlink every skill this package ships into ~/.claude/skills."""
    with run():
        planned: list[str] = []
        for name in config.SKILL_NAMES:
            link, source = config.skill_link(name), config.skill_source(name)
            if not source.is_dir():
                raise SkillInstallError(f"no skill directory at {source}; install kb from a checkout")
            if link.is_symlink() and link.resolve() == source.resolve():
                console.print(f"Already installed: {name}")
                continue
            if link.exists() and not link.is_symlink():
                raise SkillInstallError(f"{link} is a real directory, not a link; move it aside first")
            if dry_run:
                console.print(f"Would {'repoint' if link.is_symlink() else 'create'} {link} -> {source}")
                planned.append(name)
                continue
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink():
                link.unlink()
            link.symlink_to(source, target_is_directory=True)
            console.print(f"Installed: {name} ({link} -> {source})")
            planned.append(name)
        if dry_run and planned:
            console.print("Pass [bold]--no-dry-run[/bold] to do it.")
        elif planned:
            console.print("[dim]Start a new Claude Code session to pick them up.[/dim]")


@app.command()
def status(as_json: JsonOption = False) -> None:
    """Report which skill links exist and what they resolve to."""
    with run():
        rows = []
        for name in config.SKILL_NAMES:
            link, source = config.skill_link(name), config.skill_source(name)
            installed = link.is_symlink() and link.resolve() == source.resolve()
            rows.append(
                {
                    "name": name,
                    "installed": installed,
                    "link": str(link),
                    "target": str(link.resolve()) if link.is_symlink() else None,
                    "source": str(source.resolve()) if source.exists() else str(source),
                }
            )
        if as_json:
            emit_json({"skills": rows, "installed": sum(1 for row in rows if row["installed"])})
            return
        for row in rows:
            if row["installed"]:
                console.print(f"[green]ok[/green]   {row['name']}  {row['link']} -> {row['target']}")
            else:
                console.print(f"[yellow]--[/yellow]   {row['name']}  not installed")
        if not all(row["installed"] for row in rows):
            console.print("\nRun [bold]kb skill install --no-dry-run[/bold].")
