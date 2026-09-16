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

#: Superseded articles are kept as history, so they still match — but a plan whose work
#: shipped must never outrank the article describing what actually exists now.
SUPERSEDED_PENALTY = 0.4

DEFAULT_LIMIT = 10

#: Suffixes stripped to compare word stems, longest first. Deliberately a short list of
#: the endings that separate a verb from its noun — "populate" from "population",
#: "generate" from "generator". A substring search cannot bridge those, and they are
#: exactly the pairs a question and an article naturally disagree on.
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "ors", "ies", "ate", "er", "or", "es", "ed", "at", "s", "e")

#: Never stem below this, or short words collapse into each other.
_MIN_STEM = 4

_WORD = re.compile(r"[a-z0-9_]+")


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
    terms_found: list[str] = field(default_factory=list)
    terms_missing: list[str] = field(default_factory=list)
    line: int | None = None
    excerpt: str | None = None


def search(
    terms: Annotated[list[str], typer.Argument(help="Words to look for. Partial matches rank below full ones.")],
    limit: Annotated[int, typer.Option("--limit", help="How many articles to report.")] = DEFAULT_LIMIT,
    as_json: JsonOption = False,
) -> None:
    """Find which articles already cover a subject, before writing a new one."""
    with run():
        vault = config.load_config().vault
        if not vault.is_dir():
            raise VaultNotFoundError(f"no vault at {vault}; run `kb init` or set KB_VAULT")
        found = find(vault, terms)
        matches = found[:limit]
        if as_json:
            emit_json(
                {
                    "terms": terms,
                    "matches": [asdict(match) for match in matches],
                    "count": len(matches),
                    "total": len(found),
                    "by_terms_found": _breakdown(found),
                }
            )
            return
        _render(matches, terms, vault)


def _stem(word: str) -> str:
    """A crude stem: strip recognised suffixes repeatedly while enough of the word remains.

    Repeatedly, because one pass does not converge: `population` loses `ation` to give
    `popul`, while `populate` loses only `e` to give `populat`. Stripping again — `ate`,
    then `at` — brings both to `popul`, and `generator`/`generate`/`generation` to `gener`.
    The minimum stem length is what stops short words collapsing into each other.
    """
    word = word.lower()
    while True:
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
                word = word[: -len(suffix)]
                break
        else:
            return word


def _stems(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(text.lower())}


def find(vault: Path, terms: list[str]) -> list[Match]:
    """Every article containing at least one term, most terms matched first.

    Deliberately not a strict AND. A four-word query that no article satisfies used to
    return nothing while an article matching three of the four sat there unmentioned —
    and you cannot tell the difference between "nothing covers this" and "one word was
    wrong". Articles are ranked by how many distinct terms they matched, then by where
    those terms appeared; ties break on slug so the order is stable between runs.
    """
    wanted = [term.lower() for term in terms if term.strip()]
    if not wanted:
        return []
    articles, _ = schema.load_vault(vault)
    matches = [found for article in articles if (found := _score(article, wanted))]
    matches.sort(key=lambda match: (-len(match.terms_found), -match.score, match.slug))
    return matches


def _breakdown(matches: list[Match]) -> dict[str, int]:
    """How many articles matched each number of terms, e.g. {"3": 2, "2": 5}."""
    counts: dict[str, int] = {}
    for match in matches:
        key = str(len(match.terms_found))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: -int(pair[0])))


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
    stems = {name: _stems(text) for name, text in lowered.items()}
    wanted_stems = [_stem(term) for term in wanted]

    def present(term: str, stem: str, name: str) -> bool:
        return term in lowered[name] or stem in stems[name]

    pairs = zip(wanted, wanted_stems, strict=True)
    found = [term for term, stem in pairs if any(present(term, stem, name) for name in lowered)]
    if not found:
        return None
    missing = [term for term in wanted if term not in found]

    score = 0
    matched: list[str] = []
    for name, text in lowered.items():
        hits = sum(text.count(term) for term in wanted)
        hits += sum(1 for stem in wanted_stems if stem in stems[name] and stem not in text)
        if not hits:
            continue
        matched.append(name)
        score += WEIGHTS[name] * (min(hits, MAX_BODY_HITS) if name == "body" else 1)

    if article.is_superseded:
        score = max(1, round(score * SUPERSEDED_PENALTY))

    line, excerpt = _first_body_hit(article, found)
    return Match(
        slug=article.slug,
        title=article.title or article.slug,
        type=article.type,
        status=article.status,
        summary=article.summary,
        score=score,
        matched=matched,
        terms_found=found,
        terms_missing=missing,
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
        console.print(f"No article mentions any of {', '.join(terms)}. Nothing to update — this is a new article.")
        return
    total = len(terms)
    counts = _breakdown(matches)
    if total > 1:
        parts = [
            f"{n} with {'all ' if int(k) == total else ''}{k} of {total}" for k, n in counts.items()
        ]
        console.print(f"{', '.join(parts)} term(s). Strongest match first:\n")
        if str(total) not in counts:
            console.print(
                f"[yellow]Nothing matched all {total} terms[/yellow] — one of them may be wrong, "
                "or may not be the word the article uses.\n"
            )
    else:
        console.print(f"{len(matches)} article(s) mention {terms[0]}, strongest match first:\n")
    for rank, match in enumerate(matches, start=1):
        status = ""
        if match.status == "active":
            status = " [yellow](active)[/yellow]"
        elif match.status == "superseded":
            status = " [dim](superseded)[/dim]"
        where = ", ".join(match.matched)
        console.print(
            f"[bold]{rank}.[/bold] [bold]{match.slug}[/bold]{status}"
            f"  [green]{len(match.terms_found)}/{len(terms)} terms[/green]"
            f"  [dim]{match.type} · found in {where}[/dim]"
        )
        if match.terms_missing:
            console.print(f"   [dim]no mention of: {', '.join(match.terms_missing)}[/dim]")
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
