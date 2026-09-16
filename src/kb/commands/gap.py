"""`kb gap` — the learning-gaps inbox, kept in the vault.

The inbox is one article, `learning/learning-gaps`, with `status: active`. It lives in
the vault rather than beside the tool for two reasons: it is exactly the live state that
`status: active` exists for, and a gap has to be checked against the *articles* before it
is logged — you should not record a question the vault already answers.

Everything here is bookkeeping: allocate the next id, escape a cell so a pipe in the text
cannot split the row, move a row between tables, count by area. Whether something is a
genuine gap, whether it duplicates another, and which topic it belongs to are judgments,
and they stay in the skill.

Three states, which are simply which table the row is in:

    Open       noticed, not yet part of anything
    Promoted   folded into a topic article under learning/
    Learned    answered, kept so the same question is not re-logged
"""

import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .. import config, schema
from ..errors import ArticleError, KbError, VaultNotFoundError, run
from ..output import DryRunOption, JsonOption, console, emit_json

app = typer.Typer(help="Capture and organise learning gaps.", no_args_is_help=True)

OPEN = "open"
PROMOTED = "promoted"
LEARNED = "learned"
STATES = (OPEN, PROMOTED, LEARNED)

#: Heading for each state's table, in the order they appear in the article.
HEADINGS: dict[str, str] = {OPEN: "## Open", PROMOTED: "## Promoted", LEARNED: "## Learned"}

COLUMNS = ("ID", "Date", "Area", "Gap", "Note")
_HEADER = f"| {' | '.join(COLUMNS)} |"
_DIVIDER = "|" + "---|" * len(COLUMNS)

_ROW = re.compile(r"^\|(?P<cells>.*)\|\s*$")
_ID = re.compile(r"^g-(?P<number>\d{4})$")

INTRO = """Things noticed and not yet understood. Captured while working, reviewed in batches,
and folded into a topic article under `learning/` once enough of them cluster on one subject.

Managed with `kb gap`. **Do not hand-edit the tables** — a raw `|` in the text splits the
row, and ids have to stay unique.

| State | Meaning |
|---|---|
| Open | Noticed, not yet part of anything |
| Promoted | Folded into a topic article, which now owns it |
| Learned | Answered. Kept so the same question is not logged twice |
"""


@dataclass(frozen=True)
class Gap:
    """One row of the inbox."""

    id: str
    date: str
    area: str
    text: str
    note: str
    state: str

    @property
    def number(self) -> int:
        found = _ID.match(self.id)
        return int(found.group("number")) if found else 0


def _vault() -> Path:
    vault = config.load_config().vault
    if not vault.is_dir():
        raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
    return vault


def gaps_path(vault: Path) -> Path:
    return vault / f"{schema.GAPS_SLUG}.md"


def _split_cells(line: str) -> list[str]:
    """Split a table row into cells, unescaping each one.

    The unescape is the half that is easy to forget: a cell read as `a \\| b` and written
    back out would be escaped a second time into `a \\\\| b`, and again on every later
    write. Cells are held unescaped in memory and escaped exactly once on the way out.
    """
    match = _ROW.match(line)
    if not match:
        return []
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", match.group("cells"))]


def read(vault: Path) -> list[Gap]:
    """Every gap in the inbox, oldest id first. An absent inbox is simply empty.

    Sorted by id rather than by position, so the order does not depend on how the tables
    happen to be laid out in the file. Callers that want newest-first sort themselves.
    """
    path = gaps_path(vault)
    if not path.is_file():
        return []
    try:
        _, body, _ = schema.split_frontmatter(path.read_text(encoding="utf-8"))
    except ArticleError as exc:
        raise KbError(f"{path}: {exc}") from exc
    gaps: list[Gap] = []
    state: str | None = None
    for line in body.splitlines():
        heading = line.strip()
        matched = [name for name, title in HEADINGS.items() if heading == title]
        if matched:
            state = matched[0]
            continue
        if state is None or not heading.startswith("|"):
            continue
        cells = _split_cells(line)
        if len(cells) != len(COLUMNS) or cells[0] in {"ID", ""} or set(cells[0]) <= {"-"}:
            continue
        gaps.append(Gap(id=cells[0], date=cells[1], area=cells[2], text=cells[3], note=cells[4], state=state))
    gaps.sort(key=lambda gap: gap.number)
    return gaps


def write(vault: Path, gaps: list[Gap]) -> None:
    """Rewrite the inbox from the gaps given, preserving frontmatter where it exists."""
    path = gaps_path(vault)
    fields: dict[str, object]
    if path.is_file():
        front, _, _ = schema.split_frontmatter(path.read_text(encoding="utf-8"))
        loaded = yaml.safe_load(front) or {}
        fields = dict(loaded) if isinstance(loaded, dict) else {}
    else:
        fields = {"title": "Learning Gaps", "type": "learning", "status": "active", "created": date.today()}
    counts = {state: sum(1 for gap in gaps if gap.state == state) for state in STATES}
    fields.update(
        {
            "status": "active",
            "last_updated": date.today(),
            "summary": (
                f"Capture inbox for things noticed and not yet understood: {counts[OPEN]} open, "
                f"{counts[PROMOTED]} folded into a topic article, {counts[LEARNED]} answered. "
                "Live state — managed with kb gap, never quoted as settled fact."
            ),
        }
    )
    fields.setdefault("title", "Learning Gaps")
    fields.setdefault("type", "learning")
    sections = ["# Learning Gaps", "", INTRO]
    for state in STATES:
        rows = [gap for gap in gaps if gap.state == state]
        sections += ["", HEADINGS[state], ""]
        if not rows:
            sections.append("*(none)*")
            continue
        sections += [_HEADER, _DIVIDER]
        sections += [
            "| " + " | ".join(schema.table_cell(cell) for cell in (g.id, g.date, g.area, g.text, g.note)) + " |"
            for g in sorted(rows, key=lambda g: (-g.number,))
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema.render_article(fields, "\n".join(sections)), encoding="utf-8")


def _next_id(gaps: list[Gap]) -> str:
    return f"g-{max((gap.number for gap in gaps), default=0) + 1:04d}"


@app.command()
def add(
    text: Annotated[str, typer.Argument(help="The concept you did not know. Not the task it came up in.")],
    area: Annotated[str, typer.Option("--area", help="One or two words: Networking, SQL, Kubernetes…")],
    note: Annotated[str, typer.Option("--note", help="Where it came from, or a resource.")] = "",
    on: Annotated[str | None, typer.Option("--on", help="Date noticed. Defaults to today.")] = None,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Add one gap to the inbox."""
    with run():
        vault = _vault()
        gaps = read(vault)
        stamp = _date(on)
        gap = Gap(id=_next_id(gaps), date=stamp, area=area.strip(), text=text.strip(), note=note.strip(), state=OPEN)
        if not gap.text:
            raise KbError("a gap needs some text")
        if not dry_run:
            write(vault, [*gaps, gap])
        if as_json:
            emit_json({"gap": asdict(gap), "dry_run": dry_run})
            return
        console.print(f"{'Would log' if dry_run else 'Logged'} [bold]{gap.id}[/bold] ({gap.area}): {gap.text}")
        if dry_run:
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


@app.command("list")
def list_gaps(
    area: Annotated[str | None, typer.Option("--area", help="Only this area.")] = None,
    state: Annotated[str | None, typer.Option("--state", help=f"One of: {', '.join(STATES)}.")] = None,
    as_json: JsonOption = False,
) -> None:
    """List gaps, newest first, with a count per area."""
    with run():
        vault = _vault()
        if state and state not in STATES:
            raise KbError(f"--state {state} is not one of {', '.join(STATES)}")
        gaps = [
            gap
            for gap in read(vault)
            if (state is None or gap.state == state) and (area is None or gap.area.lower() == area.lower())
        ]
        gaps.sort(key=lambda gap: -gap.number)
        areas: dict[str, int] = {}
        for gap in gaps:
            areas[gap.area] = areas.get(gap.area, 0) + 1
        if as_json:
            emit_json({"gaps": [asdict(gap) for gap in gaps], "count": len(gaps), "by_area": areas})
            return
        if not gaps:
            console.print("No gaps match.")
            return
        for gap in gaps:
            marker = {OPEN: "", PROMOTED: " [dim](promoted)[/dim]", LEARNED: " [green](learned)[/green]"}[gap.state]
            console.print(f"[bold]{gap.id}[/bold] {gap.date} [cyan]{gap.area}[/cyan]{marker}")
            console.print(f"  {gap.text}", markup=False, highlight=False)
        console.print("\n[dim]" + "  ".join(f"{name}: {n}" for name, n in sorted(areas.items(), key=lambda p: -p[1])))


@app.command()
def promote(
    ids: Annotated[list[str], typer.Argument(help="Gap ids, e.g. g-0042.")],
    to: Annotated[str, typer.Option("--to", help="Topic article slug, e.g. learning/networking.")],
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Mark gaps as owned by a topic article."""
    with run():
        vault = _vault()
        target = vault / f"{to.strip('/').removesuffix('.md')}.md"
        if not target.is_file():
            raise KbError(f"no article at {target}; create it first with `kb article new`")
        title = _title(target)
        link = f"[[{to.strip('/').removesuffix('.md')}|{title}]]"
        gaps = read(vault)
        moved = _restate(gaps, ids, PROMOTED, link)
        if not dry_run:
            write(vault, gaps)
        if as_json:
            emit_json({"promoted": [asdict(gap) for gap in moved], "to": to, "dry_run": dry_run})
            return
        for gap in moved:
            console.print(f"{'Would promote' if dry_run else 'Promoted'} [bold]{gap.id}[/bold] -> {to}")
        if dry_run:
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


@app.command()
def close(
    ids: Annotated[list[str], typer.Argument(help="Gap ids, e.g. g-0042.")],
    note: Annotated[str, typer.Option("--note", help="What answered it — an article link, a source.")] = "",
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
) -> None:
    """Mark gaps as learned, so the same question is not logged twice."""
    with run():
        vault = _vault()
        gaps = read(vault)
        moved = _restate(gaps, ids, LEARNED, note.strip())
        if not dry_run:
            write(vault, gaps)
        if as_json:
            emit_json({"closed": [asdict(gap) for gap in moved], "dry_run": dry_run})
            return
        for gap in moved:
            console.print(f"{'Would close' if dry_run else 'Closed'} [bold]{gap.id}[/bold]")
        if dry_run:
            console.print("[bold]Pass --no-dry-run to do it.[/bold]")


def _restate(gaps: list[Gap], ids: list[str], state: str, note: str) -> list[Gap]:
    """Move the named gaps into `state`, in place. Raises if an id does not exist."""
    wanted = [identifier.strip() for identifier in ids]
    known = {gap.id: index for index, gap in enumerate(gaps)}
    missing = [identifier for identifier in wanted if identifier not in known]
    if missing:
        raise KbError(f"no such gap: {', '.join(missing)}")
    moved: list[Gap] = []
    for identifier in wanted:
        index = known[identifier]
        current = gaps[index]
        updated = Gap(
            id=current.id,
            date=current.date,
            area=current.area,
            text=current.text,
            note=note or current.note,
            state=state,
        )
        gaps[index] = updated
        moved.append(updated)
    return moved


def _title(path: Path) -> str:
    front, _, _ = schema.split_frontmatter(path.read_text(encoding="utf-8"))
    loaded = yaml.safe_load(front) or {}
    title = loaded.get("title") if isinstance(loaded, dict) else None
    return str(title) if title else path.stem


def _date(value: str | None) -> str:
    if value is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise KbError(f"{value!r} is not a YYYY-MM-DD date") from exc
