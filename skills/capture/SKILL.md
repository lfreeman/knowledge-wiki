---
name: capture
description: Write what a work session established into the user's knowledge base, via the `kb` CLI. Use when asked to "capture this", "add this to my knowledge base", "write this up in the wiki", "put this in my notes" (when the notes are the kb vault), or to adopt an existing document into the vault. Also use when asked what the vault already says about something, or to fix, update, or lint an article in it. Do NOT use for Anki flashcards, for a note in another app, or for writing documentation into the repository you are working in.
---

# Capture into the knowledge base

The vault is plain markdown that you write and maintain. The `kb` CLI does the bookkeeping
around it — the index, the backlink graph, frontmatter, the lint pass. You do the judgment:
what is worth keeping, whether an article already covers it, and the prose.

`kb` is already installed and on PATH. The command reference below is complete; you do not
need `--help`. Run `kb schema` for the full rules — this skill is the procedure, `SCHEMA.md`
is the specification, and it is the same file both the interactive and batch paths read.

**Every write is a preview until `--no-dry-run`.** Run bare first, show the user, then re-run
with the flag.

---

## The rule that gets skipped

> Before writing anything, search `_index.md` and the vault for an existing article on the
> subject. If one exists, **update it** and bump `last_updated` — do not create a second
> article covering the same thing. Create a new article only when nothing covers it, and add
> `related:` links both ways. **A single conversation often updates two or three existing
> articles rather than creating one.**

That last sentence is the one that gets skipped, so check it explicitly: besides the obvious
new article, what existing article did this session prove incomplete, ambiguous, or wrong? A
piece of work that produces a new incident article has usually also exposed a claim in a
system article that was stated without its version or its date. Touch both.

Searching by the exact words the user just used is not enough — the existing article may use
different vocabulary. Search the index summaries, then grep the vault for the systems, repos
and identifiers involved.

---

## Flow

1. **Read `_index.md` first.** `kb index --json` reports the counts; the file itself is at the
   vault root and is the catalog. Then grep the vault for the systems and identifiers this
   session touched.
2. **Decide update-vs-create**, per the rule above. Name out loud which articles you are going
   to touch and why, before writing anything.
3. **Classify anything you are adopting from disk** — see *Adopting an existing document*
   below. A conversation is always raw material; a file on disk may not be.
4. **Write the prose.** For a new article, write the body to a scratch file and pass it to
   `kb article new --body-file`; that way the frontmatter is generated rather than hand-typed.
   For an update, edit the file directly and then `kb article touch` it.
5. **Show the user the preview and wait.** They approve before anything is written.
6. **Write**, then run `kb index --no-dry-run`-style bookkeeping: `kb index` and `kb lint`.
   `lint` is cheap and catches the link mistakes that are invisible in raw markdown.
7. **Fix what lint reports** before finishing. A finding you leave behind is one the user
   inherits.

---

## Wikilinks — the mistake that looks correct

Links resolve by **filename**, not by the `title:` field. So `[[Some Article Title]]` matches
nothing: it renders as an unresolved link and, in Obsidian, silently creates an empty note at
the vault root when clicked. It looks right in the raw markdown, which is why it survives.

- Always `[[path/slug|Display Title]]` — the path, then the human title.
- **Inside a markdown table, escape the pipe:** `[[path/slug\|Display Title]]`. An unescaped
  `|` in a table row is a column separator and splits the link across two cells.
- Add the link in **both** directions: the new article's `related:` and the existing one's.
  `kb article link A B` writes both halves for you — use it rather than editing two files.

`kb lint` checks all three. Run it.

---

## What is worth an article

The vault competes with grep, not with a notebook. An article earns its place by holding
something that is not recoverable from the code and the commit history.

- **Capture the conclusion and the reasoning, not the transcript.** Which approaches were
  tried and rejected, and why, is the part that is expensive to rediscover. The commands that
  produced the answer usually are not.
- **Write down the thing that was surprising**, not the surrounding basics.
- **Name things exactly** — real file paths, real identifiers, real ticket ids. An article
  that says "the service" is an article nobody can act on a year later.
- **A summary is mandatory and is read far more often than the article.** It is the only thing
  in `_index.md`, so it is what decides whether anyone opens the file. Say what the article
  establishes, not what subject it is about.
- **Tag `repos:` whenever the article is about code.** It is what lets the scheduled lint pass
  tell that a repo has moved since the article was written. An article with no `repos:` can
  never be auto-checked, and that is a permanent cost, not a formality.
- **Incidents get a date-prefixed slug** — `incidents/YYYY-MM-DD-short-slug`.
- **Say what expires.** In an incident article, the facts stay true but the workaround does
  not. Write "until <version> ships, the workaround is X" rather than "the workaround is X".

---

## Adopting an existing document

A file on disk is one of four things, and getting this wrong is the main way the vault becomes
worse than nothing. `kb adopt inspect` gathers the evidence; you decide.

```bash
kb adopt inspect path/to/doc.md --json
kb adopt inspect path/to/doc.md --search ~/some/other/tree     # an additional place to look
```

It reports whether the document names the repo it is sitting in, whether that repo's own
`CLAUDE.md` or `README.md` lists it, which relative links it contains, and what points at it.
It searches the enclosing repo **and** the configured repo root, because the reference that
matters most is usually the one from a different repo — that is the one that breaks silently.

Two limits to read around. It searches for the file's **current** name, so it cannot see
references to a name the file has already been renamed away from. And when `ambiguous_name`
is true, other files share this filename — `architecture.md` and `README.md` live in half the
repositories on a machine — so a hit may point at a different file entirely. Open the cited
line before believing it.

| What it is | Signal | What to do |
|---|---|---|
| **Raw** — notes, a transcript, scraps | No structure, no audience | Absorb it into an article |
| **Finished, rightfully located** | Names its own repo; the repo lists it as project documentation | `kb adopt point` — a stub, nothing moves |
| **Finished, homeless** | Never names its own repo; the repo does not list it | `kb adopt move` |
| **Active state** | A workflow reads *and writes* it every run | `kb adopt move --status active --to learning` |

**The test: is the location meaningful?** A document under a service's `docs/` is there because
it documents that service, so it stays. A document in a scratch directory is there because
someone needed a folder, so it moves.

**Never absorb a finished, located document.** Copying it produces two versions of the truth,
and the moment the underlying system changes one of them is wrong with no way to tell which.
A pointer article cannot drift, because it does not restate the content.

**Check inbound references before moving anything.** If anything points at the document, move
it with `--source symlink` so those references keep working. This is the step that fails
silently — as a broken link in a repository nobody opens for a month.

**When it is genuinely ambiguous, ask.** A document that the repo's own docs cite *and* that
reads as general material is a real judgment call, not a coin flip.

After a move, add a line to the source repo's `CLAUDE.md` naming the new location. The repo
points out to the vault instead of holding the file.

---

## Command shapes

```bash
# read
kb index --json                     # rebuild and report counts
kb lint --json                      # findings, with file:line
kb schema                           # the full rules
kb doctor --json                    # is everything still wired up

# write a new article — body in a file, frontmatter generated
kb article new runbooks/some-slug \
  --title "Some Article Title" \
  --summary "What this establishes, in one or two sentences." \
  --repo some-service --system SomeComponent --ticket PROJ-1234 \
  --related "[[systems/other-slug|Other Article Title]]" \
  --body-file /tmp/body.md
kb article new ... --no-dry-run

# after editing an existing article by hand
kb article touch systems/other-slug --no-dry-run
kb article touch systems/a systems/b --no-dry-run     # several at once

# relate two articles — writes the link into both, and bumps both dates
kb article link systems/a runbooks/b --no-dry-run

# adopt a document from disk
kb adopt inspect path/to/doc.md --json
kb adopt point path/to/doc.md --title "..." --summary "..." --repo some-service --no-dry-run
kb adopt move  path/to/doc.md --to runbooks --title "..." --summary "..." --no-dry-run
kb adopt move  path/to/doc.md --to runbooks --source symlink --no-dry-run   # has inbound refs
kb adopt move  path/to/doc.md --to learning --status active --no-dry-run    # live state
```

If the vault is missing a directory the article needs, `kb init` creates the missing ones
and leaves everything else alone.

A document that is not markdown — HTML, a PDF — cannot carry frontmatter, so `adopt move`
will not take it. Move the file into the vault yourself and run `kb adopt point` at its new
location, which gives it a findable stub without pretending it is an article.

`--repo`, `--system`, `--ticket`, `--related` and `--source` (on `article new`) are repeatable.
`--source` on `adopt move` is different: it is `remove`, `symlink`, or `keep`, and says what
happens to the original file.

**Write the body to a scratch file rather than passing prose through shell quoting.** Article
text holds apostrophes, backticks, `$` and newlines, all of which a shell mangles silently.

---

## Two things that are not this skill's job

- **Never write to the vault unless asked.** Reading it to answer a question is always fine.
  Capturing is a thing the user asks for, at the moment the work is finished.
- **`lint` reports; it does not fix.** Neither should you, silently. Fix what you were asked to
  capture and what your own writing broke; surface the rest rather than quietly rewriting
  articles the user has not looked at.
