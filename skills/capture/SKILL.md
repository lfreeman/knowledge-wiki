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

**`kb search` is how you do this.** It reports each candidate's title, summary, type and
whether it is active, ranked by *where* the terms appear — a term in a title or `systems:`
entry means the article is about the subject; the same term in the body may be a passing
mention. That is enough to decide update-vs-create without opening any files.

Searching by the exact words the user just used is not enough — the existing article may use
different vocabulary. Search the systems, repos and identifiers involved as well, and read
the summaries of everything that comes back.

---

## Flow

1. **Search before anything else.** `kb search <terms> --json` for the subject, then again
   for the systems, repos and identifiers involved. `_index.md` at the vault root is the
   full catalog if you need to browse rather than search.
2. **Decide update-vs-create**, per the rule above. Name out loud which articles you are going
   to touch and why, before writing anything.
3. **Classify anything you are adopting from disk** — see *Adopting an existing document*
   below. A conversation is always raw material; a file on disk may not be.
4. **Write the prose.** For a new article, write the body to a scratch file and pass it to
   `kb article new --body-file`; that way the frontmatter is generated rather than hand-typed.
   For an update, edit the file directly and then `kb article touch` it.

   **Read what `kb article new` prints before the preview.** It lists existing articles
   sharing any `systems:`, `repos:` or `tickets:` value with the one you are about to write.
   That is the update-vs-create question asked again at the last possible moment — a search
   run earlier in the session cannot see what landed since. If one of them should have been
   updated instead, stop and update it.

   **Never hand-edit frontmatter arrays.** They are single long lines of flow-style YAML.
   `--related` writes the reverse link into the other article for you, `kb article link` is
   safe to run afterwards because it de-duplicates, and `kb article tag` adds or removes
   `systems:`, `repos:` and `tickets:` on articles that already exist.
5. **Show the user the preview and wait.** They approve before anything is written.
6. **Write**, then run `kb index` and `kb lint`. **`kb index` takes no `--no-dry-run`** —
   it regenerates derived data and writes by default, unlike every other write command.
   `lint` is cheap and catches the link mistakes that are invisible in raw markdown.
7. **Close the gaps this answered.** Capture is the moment the inbox should shrink, and it
   is the step most likely to be skipped because the writing already feels finished. Run
   `kb gap list --state open --json` and look for gaps the new article answers — they are
   often ones logged earlier in this very session.

   ```bash
   kb gap close g-0051 g-0052 --note "[[runbooks/some-slug|Some Article Title]]" --no-dry-run
   kb gap promote g-0060 --to learning/<topic> --no-dry-run   # if it belongs to a topic instead
   ```

   Close a gap only when the article genuinely answers it — closing is a claim the user now
   knows it. Say which ids you closed in your end-of-turn note.

   **The answer does not have to be in the vault.** A gap can be genuinely answered by a
   published document, a card deck, or a conversation the user worked through. Close it, and
   put the real location in `--note` — a URL or a deck name instead of a wikilink. What
   matters is that a future reader can find what answered it.
8. **Fix what lint reports** before finishing. A finding you leave behind is one the user
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

- **Create the article you are linking to first.** A link written before its destination
  exists points at a slug you have not committed to yet, and `kb adopt move --to` decides the
  destination directory — and therefore the slug — at the moment you run it. Change your mind
  about the directory and every link written earlier is now wrong, in files already on disk.

`kb lint` checks all four, reporting the last as `link-broken`. Run it — and never skip it
after an adoption, which is the step most likely to have moved a slug out from under a link.

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
- **Incidents get a date-prefixed slug** — `incidents/YYYY-MM-DD-short-slug`. That date
  **sets `created:`**: `kb article new` reads it from the slug, so a backdated article needs
  no extra flag. Use `--created YYYY-MM-DD` only for an undated slug that describes older
  work; if both are given and disagree, `kb` warns and `--created` wins.
- **Say what expires.** In an incident article, the facts stay true but the workaround does
  not. Write "until <version> ships, the workaround is X" rather than "the workaround is X".
- **Retire, do not delete.** When an article stops describing how things are — a plan whose
  work shipped, a design that was replaced — set `status: superseded`, say in it what
  replaced it, and link there. It keeps ranking below current material in search instead of
  competing with it, and lint stops checking its age. Deleting it would lose the reasoning,
  which is the expensive half.

---

## Adopting an existing document

A file on disk is one of four things, and getting this wrong is the main way the vault becomes
worse than nothing. `kb adopt inspect` gathers the evidence; you decide.

```bash
kb adopt inspect path/to/doc.md --json
kb adopt inspect path/to/doc.md --search ~/some/other/tree     # an additional place to look
```

It reports whether the document names the repo it is sitting in, whether that repo's own
`CLAUDE.md` or `README.md` lists it, whether git tracks it, which relative links it contains
— **including the ones that are already broken** — and what points at it.
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
| **Finished, rightfully located** | Names its own repo in prose; the repo lists it; the repo tracks it | `kb adopt point` — a stub, nothing moves |
| **Finished, homeless** | Never names its own repo; not listed; often **not tracked by git** | `kb adopt move` |
| **Active state** | A workflow reads *and writes* it every run | `kb adopt move --status active --to learning` |
| **Claimed but uncommitted** | `signals_conflict: true` — names its own repo, or the repo lists it, *and* git does not track it | Not decidable from the evidence. Ask |

**`tracked_by_git: false` is the strongest single signal.** A repository that does not track
a document is not claiming it, and that document has no history and no backup — moving it
into the vault is a rescue, not a reorganisation. Say so when you report it.

**Except when the repo's own text claims it anyway.** A document written into a service's
`docs/` and never committed reads as rightfully located *and* as homeless at once, and it is
a common state — a whole directory of drafts can be untracked. `kb adopt inspect` reports
that combination as `signals_conflict: true`. Do not resolve it from the evidence, because
the evidence does not contain the answer: what settles it is whether the repo is *meant* to
own the document, which only the user knows. Ask, and say which way each signal points.

`names_own_repo` counts prose only; a repo name inside a code block or backticks is a
dependency coordinate, not the document claiming ownership.

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

**If the source directory is being deleted, that pointer is worthless — check what lives
only there first.** A folder's own index or conventions file routinely holds content that
exists nowhere else: which repo owns which spec, the standing assumptions a playbook was
written against, canonical commit references. Read it before it goes, and fold whatever is
load-bearing into an article. Both adoption runs so far turned up exactly this.

---

## Command shapes

```bash
# read
kb search <terms> --json            # which articles already cover this — run this first
kb index --json                     # rebuild and report counts
kb lint --json                      # findings, with file:line
kb schema                           # the full rules
kb doctor --json                    # is everything still wired up

# write a new article — body in a file, frontmatter generated
kb article new runbooks/some-slug \
  --title "Some Article Title" \
  --summary "What this establishes, in one or two sentences." \
  --created 2026-01-31 \
  --repo some-service --system SomeComponent --ticket PROJ-1234 \
  --related "[[systems/other-slug|Other Article Title]]" \
  --body-file /tmp/body.md
kb article new ... --no-dry-run

# close the gaps the new article answers
kb gap list --state open --json
kb gap close <id>... --note "[[dir/slug|Title]]" --no-dry-run

# after editing an existing article by hand
kb article touch systems/other-slug --no-dry-run
kb article touch systems/a systems/b --no-dry-run     # several at once

# add tags to articles that already exist, rather than editing the YAML by hand
kb article tag systems/a systems/b --system geohash --repo some-service --no-dry-run

# relate two articles — writes the link into both, and bumps both dates
kb article link systems/a runbooks/b --no-dry-run

# adopt a document from disk
kb adopt inspect path/to/doc.md --json
kb adopt point path/to/doc.md --title "..." --summary "..." --repo some-service --no-dry-run
kb adopt move  path/to/doc.md --to runbooks --title "..." --summary "..." --no-dry-run
kb adopt move  path/to/doc.md --to runbooks --source symlink --no-dry-run   # has inbound refs
kb adopt move  path/to/doc.md --to learning --status active --no-dry-run    # live state

# several at once — one JSON object per document, same keys as the options
kb adopt move --from-file /tmp/moves.json --no-dry-run
```

**Use `--from-file` for more than two documents.** Ten options on one command line is
error-prone for a single file and unbearable across a directory. The keys are `path`, `to`,
`title`, `summary`, `type`, `status`, `slug`, `created`, `repos`, `systems`, `tickets`,
`related`, `note`, `source`.

`adopt move` refuses to remove a file an editor still has open, because saving from that
buffer afterwards would write the old copy back to a path that no longer exists.

If the vault is missing a directory the article needs, `kb init` creates the missing ones
and leaves everything else alone.

A document that is not markdown — HTML, a PDF — cannot carry frontmatter, so `adopt move`
will not take it. Move the file into the vault yourself and run `kb adopt point` at its new
location, which gives it a findable stub without pretending it is an article.

### Every option, so you never have to probe for one

Each list is complete. Every write also takes `--dry-run/--no-dry-run`, and every command
takes `--json`.

| Command | Arguments | Options |
|---|---|---|
| `kb article new` | `<dir>/<slug>` | `--title` `--summary` `--type` `--status` `--created` `--body-file` `--path` · repeatable: `--repo` `--system` `--ticket` `--related` `--source` |
| `kb article link` | `<slug> <slug>` | `--one-way` |
| `kb article tag` | `<slug>…` | `--system` `--repo` `--ticket` (all repeatable) · `--remove` |
| `kb article touch` | `<slug>…` | `--on` |
| `kb adopt inspect` | `<path>` | `--search` (repeatable) |
| `kb adopt move` | `<path>` | `--to` `--title` `--summary` `--type` `--status` `--slug` `--created` `--note` `--source` `--from-file` · repeatable: `--repo` `--system` `--ticket` `--related` |
| `kb adopt point` | `<path>` | `--title` `--summary` `--slug` · repeatable: `--repo` `--system` `--ticket` `--related` |
| `kb gap add` | `"<text>"` | `--area` `--note` `--on` |
| `kb gap list` | — | `--area` `--state` |
| `kb gap promote` | `<id>…` | `--to` |
| `kb gap close` | `<id>…` | `--note` |
| `kb search` | `<terms>…` | `--limit` |

`kb index` is the one write with no `--dry-run`: it regenerates derived data, so a
preview-first default would be friction on the most-run command.

### What `--json` returns

Top-level keys, so you never have to probe the shape. Every write also carries `dry_run`.

| Command | Top-level keys |
|---|---|
| `kb article new` | `slug` `target` `article` `overlaps[]` `backlinks[]` `dry_run` |
| `kb article link` | `changed[]` `dry_run` |
| `kb article tag` | `articles[]` `removed` `dry_run` |
| `kb article touch` | `changed[]` `dry_run` |
| `kb adopt inspect` | a flat object — `path` `lines` `heading` `repo` `repo_name` `names_own_repo` `listed_in_repo_docs[]` `outbound_relative[]` `outbound_broken[]` `inbound[]` `searched[]` `ambiguous_name` `tracked_by_git` `signals_conflict` |
| `kb adopt move` | `moves[]` `dry_run` — each move has `action` `source` `target` `source_action` `links_absolutised[]` `backlinks[]` `article` |
| `kb adopt point` | one move object, flat, plus `dry_run` |
| `kb gap add` | `gap` `dry_run` |
| `kb gap list` | `gaps[]` `count` `by_area` |
| `kb gap promote` | `promoted[]` `to` `dry_run` |
| `kb gap close` | `closed[]` `dry_run` |
| `kb search` | `matches[]` `count` `total` `terms[]` `by_terms_found` |
| `kb index` | `articles` `directories` `backlinks` `index` `backlinks_file` `unreadable[]` `dry_run` |
| `kb lint` | `findings[]` `errors` `warnings` |

Every gap — in `gaps[]`, `promoted[]`, `closed[]` and `gap` — is
`{id, date, area, text, note, state}`. Every search match carries `slug` `title` `type`
`status` `summary` `score` `matched[]` `terms_found[]` `terms_missing[]` `line` `excerpt`
`inbox_mention`.

Two traps in that table. **`--source` means different things**: on `article new` it is a
repeatable raw-entry id, and on `adopt move` it is one of `remove`, `symlink` or `keep`,
saying what happens to the original file. And **`--type` is the article type**
(`runbook`, `incident`, …), not a file type.

**Write the body to a scratch file rather than passing prose through shell quoting.** Article
text holds apostrophes, backticks, `$` and newlines, all of which a shell mangles silently.

---

## Two things that are not this skill's job

- **Never write to the vault unless asked.** Reading it to answer a question is always fine.
  Capturing is a thing the user asks for, at the moment the work is finished.
- **`lint` reports; it does not fix.** Neither should you, silently. Fix what you were asked to
  capture and what your own writing broke; surface the rest rather than quietly rewriting
  articles the user has not looked at.
