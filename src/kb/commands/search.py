"""`kb search` — which existing articles already cover this?

This command exists for one decision: update-vs-create. The capture rule opens with
"search the vault for an existing article on the subject", and that is the step most
likely to be skipped — not through carelessness, but because a later discussion uses
different vocabulary than the article that already covers it.

So matching is deliberately generous about *where* it looks and strict about *ranking*.
A term in a title or a `systems:` entry is strong evidence the article is about the
subject; the same term buried in the body is weak evidence. Sorting by that difference
is the whole value: the top row is the article you were about to duplicate.

No model is involved. A model decides whether the match means the same thing.
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from .. import config, schema
from ..errors import VaultNotFoundError, run
from ..output import JsonOption, console, emit_json

#: How much a hit in each place counts. A title match is about the subject; a body match
#: may be a passing mention, so it ranks below every structured field.
WEIGHTS: dict[str, int] = {
    "title": 10,
    "summary": 6,
    "systems": 5,
    "repos": 4,
    "tickets": 4,
    "slug": 3,
    "body": 1,
}

#: A body can mention a term fifty times without being about it, so its contribution caps.
MAX_BODY_HITS = 3

DEFAULT_LIMIT = 10


@dataclass
class Match:
    """One article that matched, and the evidence for it."""

    slug: str
    title: str
    type: str
    status: str
    summary: str
    score: int
    matched: list[str] = field(default_factory=list)
    line: int | None = None
    excerpt: str | None = None


def search(
    terms: Annotated[list[str], typer.Argument(help="Words to look for. An article must contain all of them.")],
    limit: Annotated[int, typer.Option("--limit", help="How many articles to report.")] = DEFAULT_LIMIT,
    as_json: JsonOption = False,
) -> None:
    """Find which articles already cover a subject, before writing a new one."""
    with run():
        vault = config.load_config().vault
        if not vault.is_dir():
            raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
        matches = find(vault, terms)[:limit]
        if as_json:
            emit_json({"terms": terms, "matches": [asdict(match) for match in matches], "count": len(matches)})
            return
        _render(matches, terms, vault)


def find(vault: Path, terms: list[str]) -> list[Match]:
    """Every article containing all the terms, best first.

    Ties break on slug so the order is stable between runs rather than filesystem-ordered.
    """
    wanted = [term.lower() for term in terms if term.strip()]
    if not wanted:
        return []
    articles, _ = schema.load_vault(vault)
    matches = [found for article in articles if (found := _score(article, wanted))]
    matches.sort(key=lambda match: (-match.score, match.slug))
    return matches


def _score(article: schema.Article, wanted: list[str]) -> Match | None:
    """Score one article, or None when it does not contain every term."""
    haystacks = {
        "title": article.title,
        "summary": article.summary,
        "systems": " ".join(article.list_field("systems")),
        "repos": " ".join(article.list_field("repos")),
        "tickets": " ".join(article.list_field("tickets")),
        "slug": article.slug.replace("-", " ").replace("/", " "),
        "body": article.body,
    }
    lowered = {name: text.lower() for name, text in haystacks.items()}
    if not all(any(term in text for text in lowered.values()) for term in wanted):
        return None

    score = 0
    matched: list[str] = []
    for name, text in lowered.items():
        hits = sum(text.count(term) for term in wanted)
        if not hits:
            continue
        matched.append(name)
        score += WEIGHTS[name] * (min(hits, MAX_BODY_HITS) if name == "body" else 1)

    line, excerpt = _first_body_hit(article, wanted)
    return Match(
        slug=article.slug,
        title=article.title or article.slug,
        type=article.type,
        status=article.status,
        summary=article.summary,
        score=score,
        matched=matched,
        line=line,
        excerpt=excerpt,
    )


def _first_body_hit(article: schema.Article, wanted: list[str]) -> tuple[int | None, str | None]:
    """The first body line containing any term, as `file:line` plus the text around it."""
    for number, content in enumerate(article.body.splitlines(), start=1):
        lowered = content.lower()
        for term in wanted:
            position = lowered.find(term)
            if position < 0:
                continue
            start = max(0, position - 40)
            excerpt = content[start : position + len(term) + 60].strip()
            return number + article.body_offset, ("…" if start else "") + excerpt
    return None, None


def _render(matches: list[Match], terms: list[str], vault: Path) -> None:
    """Paths are printed absolute, because a terminal only opens an absolute one.

    A relative `some/article.md:18` is not resolvable from wherever the shell happens to
    be, so the terminal guesses it is a URL and hands it to a browser.
    """
    if not matches:
        console.print(f"No article mentions {' and '.join(terms)}. Nothing to update — this is a new article.")
        return
    console.print(f"{len(matches)} article(s) mention {' and '.join(terms)}, strongest match first:\n")
    for rank, match in enumerate(matches, start=1):
        status = " [yellow](active)[/yellow]" if match.status == "active" else ""
        where = ", ".join(match.matched)
        console.print(
            f"[bold]{rank}.[/bold] [bold]{match.slug}[/bold]{status}"
            f"  [green]score {match.score}[/green]  [dim]{match.type} · found in {where}[/dim]"
        )
        if match.summary:
            console.print(f"   {_clip(match.summary, 150)}")
        if match.line and match.excerpt:
            # The excerpt is arbitrary article text and routinely contains [[wikilinks]],
            # which Rich would read as console markup and swallow.
            console.print(f"   [cyan]{vault / match.slug}.md:{match.line}[/cyan]  {escape(_clip(match.excerpt, 90))}")
        console.print()
    console.print("[dim]Update the article that already covers this rather than writing a second one.[/dim]")


def _clip(text: str, width: int) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= width else flat[: width - 1] + "…"
