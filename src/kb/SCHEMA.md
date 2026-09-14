# SCHEMA.md — how this knowledge base is structured

The rules for reading and writing the vault. `capture` (one conversation, interactive) and
`ingest` (a whole corpus, batch) are the same procedure at different scale, and they both
read this file, so they cannot drift apart.

This file ships inside the `kb` package. It is **never copied into a vault** — upgrading
`kb` upgrades the rules everywhere at once. Read it from the installed package:

```bash
kb schema          # print this file
kb schema --path   # print where it lives
```

---

## 1. Layout

```
<vault>/
  _index.md                 master catalog — an agent's entry point (GENERATED)
  _backlinks.json           reverse link index                      (GENERATED)
  _absorb_log.json          which source entries have been ingested (GENERATED)
  raw/entries/              one .md per absorbed source entry
  incidents/                what happened, why, what to do about it
  systems/                  how a thing works, usually across services
  runbooks/                 operational procedures
  guides/                   long-form technical references that live HERE
  learning/                 active learning plans — live state, mutates every session
  research/                 open investigations, reading notes, comparisons
  journal/                  dated entries synthesized from a journal corpus
  reference/                pointer articles → documents that stay in their own repo
```

**`guides/` and `learning/` hold the documents themselves, not pointers.** That is the
distinction that decides whether a file moves. `reference/` is for documents that belong
next to their code and therefore stay in the repo; `guides/` and `learning/` are for
documents that have no other rightful home.

Files beginning with `_` are generated. **Never hand-edit them.** Run `kb index`.

---

## 2. Article frontmatter

Every article is a markdown file whose first line is `---`, followed by a YAML block,
followed by `---`, followed by the document.

```yaml
---
title: Article Title
type: system | incident | runbook | guide | learning | reference | research | journal | ticket | concept
status: stable | active
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
summary: One or two sentences. This is what an agent reads in _index.md before deciding to open the file.
tickets: [PROJ-1234]
repos: [some-service]
systems: [ComponentName, some_table, some_metric]
related: ["[[runbooks/some-slug|Some Article Title]]"]
sources: ["entry-id-1", "entry-id-2"]
path: <only for type: reference — where the real document lives>
note: <optional free text about the article's placement>
---
```

### Required on every article

`title`, `type`, `status`, `created`, `last_updated`, `summary`.

`type: reference` additionally requires `path`.

### Field rules

| Field | Rule |
|---|---|
| `title` | The human title. Does **not** determine the filename or resolve links. |
| `type` | One of the values listed above. Describes the document; see §3 for its home. |
| `status` | `stable` by default. `active` marks a document that mutates every session. |
| `created` / `last_updated` | `YYYY-MM-DD`. Bump `last_updated` on every edit. |
| `summary` | Plain prose, no markdown, no line breaks. Rendered into `_index.md`. |
| `tickets` / `repos` / `systems` | Flat lists of bare identifiers. `repos` is what makes an article auto-checkable — see §8. |
| `related` | List of quoted wikilinks in full `[[path/slug\|Title]]` form. Add links in **both** directions. |
| `sources` | Raw entry IDs, never file paths. |
| `path` | Absolute or `~`-relative path to the real document. `reference/` only. |

### Filenames

Filenames are **slugs**: lowercase, hyphen-separated, `.md`. They stay slugs because git,
grep and scripts all work better with them. The human title lives in `title:` and in the
wikilink alias.

Incident articles are prefixed with their date: `incidents/YYYY-MM-DD-short-slug.md`.

---

## 3. Which directory a type lives in

| `type` | Directory |
|---|---|
| `system` | `systems/` |
| `incident` | `incidents/` |
| `runbook` | `runbooks/` |
| `guide` | `guides/` |
| `learning` | `learning/` |
| `reference` | `reference/` |
| `research` | `research/` |
| `journal` | `journal/` |
| `ticket`, `concept` | No dedicated directory. File under the directory of the subject. |

The directory is what `_index.md` groups by. `type` is a label on the document.

---

## 4. Wikilinks — always `[[path/slug|Display Title]]`

**A bare `[[Display Title]]` is a defect, not a style preference.**

Links are resolved by **filename**, not by the `title:` field. Since filenames are slugs and
titles are prose, a bare title link matches nothing: it renders as an unresolved link and, in
Obsidian, silently creates an empty note at the vault root when clicked. A vault written that
way has an entirely empty backlink graph and looks correct in the raw markdown.

Three rules follow, and all three are enforced by `kb lint`:

1. **Always carry the path.** `[[runbooks/some-slug|Some Article Title]]`, never
   `[[Some Article Title]]`. Omit the `.md`. The path is relative to the vault root.
2. **Inside a markdown table, escape the pipe:** `[[runbooks/some-slug\|Some Article Title]]`.
   An unescaped `|` in a table row is a column separator — it splits the link across two
   cells and destroys it. Most links live in tables, because `_index.md` is entirely tables.
   Outside a table the plain unescaped form is correct.
3. **Generate tables with minimal, unpadded rows** — `| a | b |`, never column-aligned.
   An editor that reflows a table pushes the alignment padding *inside* the wikilinks and
   breaks them. Leaving nothing to reflow is the fix.

---

## 5. Raw entry format

One file per absorbed source entry, under `raw/entries/`.

```yaml
---
id: <unique, stable, and the value articles cite in sources:>
date: YYYY-MM-DD
source_type: bear | claude-code-transcript | file | journal
tags: []
---
<entry text, verbatim>
```

Raw entries are the audit trail. Articles cite them by `id`. Never edit one after writing it.

---

## 6. The four kinds of source

Every input is exactly one of these. Classifying wrong is the main way the vault becomes
worse than nothing, so classify before doing anything else.

| Kind | What it looks like | Action |
|---|---|---|
| **1. Raw** | Notes, journal entries, session transcripts, research scraps | **Absorb.** Synthesize into articles. |
| **2. Finished, and rightfully located** | A complete document sitting next to the code it documents | **Point at it.** Write a `type: reference` stub. Never move it, never restate it. |
| **3. Finished, but homeless** | A complete document on a subject tied to no one repo, sitting wherever it was dropped | **Move it into the vault** verbatim, with frontmatter prepended. First-class content. |
| **4. Active state** | A document a workflow reads and writes on every run | **Move to `learning/` with `status: active`.** |

### The test that decides move vs. point

**Is the location meaningful?** A document under a service's `docs/` directory is there
because it documents that service — meaningful, so it stays and gets a pointer. A document
in a scratch directory is there because its author needed a folder — not meaningful, so it
moves.

### A cheap heuristic that works

**A homeless document never names its own repo.** Read the first screen: if the document
says which service it is about, it is probably kind 2. If it never mentions it, kind 3.
Corroborate against the repo's own `CLAUDE.md` or `README.md` — a document the repo does
not list as project documentation is a strong kind-3 signal.

### Why kind 2 is never absorbed

Absorbing a finished document produces an article that duplicates it. The moment the
underlying system changes, one of the two is wrong and there is no way to tell which.
Pointer articles cannot drift, because they do not restate the content.

### What separates kind 4 from kind 3

Two properties. Kind 4 documents **mutate continuously**, so any summary of their contents
is stale within a day; and they are often **invoked by path**, so moving one breaks the
workflow that reads it unless its self-references are fixed in the same commit.

Claude reads a `status: active` document as *current position*, writes back to it, and
**never cites it as settled fact**. `kb lint` never flags one as stale for changing.

### When it is genuinely ambiguous, ask

A document that is cited by a repo's own docs *and* reads as general study material is a
real judgment call. Ask. Do not guess.

---

## 7. The adoption procedure

`capture` (a conversation), `adopt` (a file or directory) and `ingest` (a corpus) all run
these steps. They differ only in what they are pointed at.

**1. Read it, and check whether it mentions the repo it is sitting in.** (§6 heuristic.)

**2. Classify** per §6: raw / finished-and-located / finished-but-homeless / active state.
Ask when ambiguous rather than guessing.

**3. Check the reference web in BOTH directions — before moving anything.**
This step is easy to skip and expensive to skip, because skipping it fails silently: a
broken link in a repo nobody opens for a month.

- **Outbound** — does the document point at files by *relative* path? Those become
  meaningless once it lives elsewhere. **Rewrite them as absolute paths.** An absolute path
  reads correctly from the vault *and* from the repo, so this is a pure win.
- **Inbound** — does anything point *at* this document? Grep the filename across the
  repositories and config that could reference it.

A document's *location* can be accidental while its *reference web* is not. Budget for the
link work, not just the move.

**4. Act on the classification.**

| Kind | Action |
|---|---|
| Homeless | Move into `guides/` / `runbooks/` / `systems/`, prepend frontmatter, absolutise outbound references |
| Homeless **with inbound references** | As above, **plus symlink the old path to the new file**, so inbound references keep working with no edits elsewhere |
| Located | Write a `reference/` stub carrying `path:`. Move nothing, restate nothing |
| Raw | Absorb into an article |
| Active state | Move to `learning/` with `status: active`, and fix the document's own self-references in the same commit so it does not lie about where it lives |

**5. Add the repo-side pointer.** When a document leaves a repo, that repo's `CLAUDE.md`
gets a line naming the new location and saying to keep it updated. The repo points *out* to
the vault instead of holding the file.

**6. Rebuild the generated files** with `kb index` — never by hand.

### Two symlink gotchas

- **`find` does not follow symlinks by default.** A sweep using `find -type f` will *miss* a
  symlinked document. Use `find -L`, or handle symlinks explicitly.
- **`git add` stores a symlink as a path string, not content.** It dangles on any other
  machine and in CI. Harmless while the target is untracked; a landmine once it is not.

---

## 8. The capture rule — update, don't duplicate

> Before writing anything to the knowledge base, search `_index.md` and the vault for an
> existing article on the subject. If one exists, **update it** and bump `last_updated` — do
> not create a second article covering the same thing. Create a new article only when
> nothing covers it, and add `related:` links both ways. A single conversation often
> updates two or three existing articles rather than creating one.

The last sentence is the one that gets skipped. A single piece of work routinely warrants a
new article **and** exposes a gap in an existing one — an unversioned claim, a rule stated
without its date, a section that a later decision superseded. Touch both.

**This rule is not a guarantee.** If a later discussion uses different vocabulary than the
index summary, the existing article gets missed and a duplicate gets written. That is what
`lint` is for: the instruction makes it *usually* right, `lint` makes it *eventually* right.
Both are required; neither is sufficient.

### Never write to the vault unasked

Reading the vault is always fine. Writing happens only when explicitly asked.

---

## 9. What `lint` checks

Two passes. The cheap pass is a pure script and runs constantly; the expensive pass needs a
model and runs on a schedule.

**`lint` never silently fixes anything. It reports.**

### Cheap pass — no model, runs on every capture and in a pre-commit hook

- A bare `[[Display Title]]` wikilink (§4 rule 1)
- An unescaped `|` inside `[[...]]` on a table row (§4 rule 2)
- A wikilink whose target file does not exist
- A `reference/` article whose `path:` target does not exist
- Missing required frontmatter field (§2)
- A malformed date, or `last_updated` earlier than `created`
- Duplicate `title:` across two articles
- An orphan — an article nothing links to
- `last_updated` older than the staleness threshold — **skipped for `status: active`**
- An article in a directory §1 does not define

### Expensive pass — needs a model, runs weekly or monthly

- Does this runbook still match the code?
- Do two articles contradict each other?
- Has this decision been superseded?

**Scope the expensive pass with git history.** An article tagged `repos: [some-service]`
with `last_updated: 2026-07-01` can only have gone stale if that repo has commits after that
date. If the repo has not moved, the article cannot be wrong. That turns "re-verify
everything" into "re-verify the handful whose underlying code actually changed."

### The honest ceiling

| Article kind | Ages? | Can lint check it? |
|---|---|---|
| About code or systems | Yes | **Yes** — read the code, compare. This is the whole safety net. |
| About an incident | The facts don't; the *advice* does | **Partially.** What happened stays true. "The workaround is X" expires the day the fix ships, and lint only catches that if something tells it the fix shipped. |
| About a decision | The fact doesn't; it can be **superseded** | **No.** A decision stays historically true. Only a human knows it was later reversed. |

**An article with no `repos:` tag can never be auto-checked.** That is the price of the
incident and decision categories. Accept it explicitly rather than pretending otherwise.

**Stated plainly: the system can tell you when something is old. It can only sometimes tell
you when something is wrong.**

---

## 10. Generated files

### `_index.md`

The master catalog and an agent's entry point. Grouped by directory, one table per
directory, columns: Article, Status, Systems, Summary.

`kb index` **always regenerates and overwrites it, and never merges.** The index is derived
data; any other copy is disposable by definition. Refusing to write because the file looks
modified would leave a broken index in place, which is worse.

Rows are emitted minimal and unpadded (§4 rule 3).

### `_backlinks.json`

The reverse link index: for each article, which articles link to it.

```json
{
  "runbooks/some-slug": ["reference/some-service", "systems/some-system"]
}
```

Keys and values are vault-relative slug paths with no `.md`, matching the wikilink target
form. An article with no inbound links does not appear.

### `_absorb_log.json`

Which source entries have already been ingested, so a re-run does not duplicate work and a
run that dies partway can resume.

```json
{
  "entries": {
    "entry-id-1": {"absorbed": "YYYY-MM-DD", "articles": ["systems/some-system"]}
  }
}
```

---

## 11. Retrieval — how the vault is meant to be read

- Walk `_index.md` first. Open only the articles it points at.
- **Follow a `reference/` article's `path:` to the real document.** Never answer from the
  stub's summary — the stub deliberately does not restate the content.
- Treat `status: active` articles as *current position*, never as settled fact.
- Cite the article path in the answer, so the reader knows which note it came from.
- Never write to the vault unasked.
