---
name: gap
description: Capture something the user did not know into their learning-gaps inbox in the kb vault, or sweep a finished session for what they did not know. Use when the user types /gap, says "add a gap", "log this to learn", "I should learn X", "note that I didn't know X", or asks what they should study. Also use to review a past session for missed gaps. Do NOT use for Anki flashcards, or for capturing knowledge itself — that is the capture skill.
---

# Capture a learning gap

Gaps live in the vault, in the article `learning/learning-gaps`, and are managed with
`kb gap`. Never hand-edit that file: a raw `|` in the text splits the row, and ids have to
stay unique. `kb` is already installed.

**Every write is a preview until `--no-dry-run`.**

---

## Two ways in

**One gap, now.** The user says `/gap <thing>`, or something in conversation was clearly
new to them. Log it and get out of the way — this usually runs mid-task.

**A sweep, afterwards.** The user asks what they missed, or a session is ending, or they
name a past session. Read back over it and propose what they did not know. **This is the
mode that matters**, because the first one keeps missing things: one real subject ran for
eleven days across three sessions and produced eight questions and zero logged gaps,
because no single moment felt like "a gap".

---

## Logging one gap

1. **Check the vault first.** `kb search <terms> --json`. If an article already answers it,
   say which one and do not log — the user does not need to study what they have written
   down. This is the step that did not exist before and it is not optional.
2. **Check the inbox.** `kb gap list --json`. If a near-duplicate is open, say which id
   covers it and stop. Ids are stable, so name it: "g-0042 already covers this."
3. **Write the concept, not the task.** "Window-function syntax", never "the report query
   I was writing". A year from now the task means nothing and the concept still does.
4. **Make it self-contained.** It should be readable cold, months later, by someone who
   was not in this session. Name the real identifiers. Two or three sentences is normal —
   several existing gaps are a paragraph and are better for it.
5. **Area** in one or two words: `Networking`, `SQL`, `Kubernetes`, `Spring Boot`. Reuse an
   area that already exists rather than inventing a near-synonym — `kb gap list --json`
   reports the counts, and clustering is what makes a topic visible.
6. **Log it**, then confirm in one line.

```bash
kb search "<terms>" --json
kb gap list --json
kb gap add "<the concept, self-contained>" --area "Networking" --note "<where it came from>" --no-dry-run
```

Do not teach the topic here. This skill captures.

---

## Sweeping a session

Run when asked, at the end of a substantial session, or over a named transcript.

1. **Read back over the session.** For a past one, transcripts are JSON Lines under
   `~/.claude/projects/<project>/<session-id>.jsonl`; the user's turns are the records with
   `type: "user"`.
2. **Look for the four shapes** — these are what a gap actually looks like in the wild:
   - **A question asked** — "what is X", "how does Y work".
   - **A misconception corrected.** The highest-value kind. The user believed something
     that turned out to be wrong, so this is a gap they did not know they had.
   - **A subject returned to.** Asked about across days or sessions. Recurrence is the
     strongest signal there is, and it is invisible in any single session.
   - **Visible struggle** — repeated attempts at a command, a query, a config.
3. **Ignore** what they clearly already knew, one-off trivia, and anything the vault
   already answers. Check with `kb search`.
4. **Propose the list and wait.** Show each candidate as one line with its area. The user
   approves before anything is logged.
5. **Log the approved ones**, then say whether any area now has enough to justify a topic —
   see below.

---

## When gaps cluster, make a topic

Three or four gaps in one area means the subject is real and deserves a home.

A **topic is one article** under `learning/`, with `status: active`. It starts as a list of
what is not understood yet and grows as answers arrive. If it ever earns a curriculum —
ordered steps, a progress log — those go in **the same file**. There is no second document
and nothing is migrated. That is deliberate: creating a heavy plan is why nothing ever got
promoted before.

```bash
kb article new learning/<topic> --title "<Topic> — Topic" --status active \
  --summary "..." --body-file /tmp/body.md --no-dry-run
kb gap promote g-0012 g-0019 g-0031 --to learning/<topic> --no-dry-run
```

Give the article a **Covers** line naming the areas it owns, so later gaps route to it.

Build it around something the user actually operates, not a syllabus. A chain they debug
weekly is a better curriculum than a textbook, because its failures already cost them time.

---

## Closing a gap

When something answers a gap, record what did. This is what stops the same question being
logged a third time.

```bash
kb gap close g-0042 --note "[[guides/s3-streaming|AWS S3 Streaming]] §6.1" --no-dry-run
```

**The answer does not have to be in the vault.** A published document, a card deck, or a
conversation the user worked through can genuinely close a gap. Put the real location in
`--note` — a URL or a deck name instead of a wikilink — so a future reader can still find
what answered it.

---

## Command reference

Each list is complete. Every write also takes `--dry-run/--no-dry-run`, and every command
takes `--json`.

| Command | Arguments | Options |
|---|---|---|
| `kb gap add` | `"<text>"` | `--area` `--note` `--on` |
| `kb gap list` | — | `--area` `--state` (`open`, `promoted`, `learned`) |
| `kb gap promote` | `<id>…` | `--to` |
| `kb gap close` | `<id>…` | `--note` |
| `kb search` | `<terms>…` | `--limit` |
| `kb article new` | `<dir>/<slug>` | `--title` `--summary` `--type` `--status` `--created` `--body-file` `--path` · repeatable: `--repo` `--system` `--ticket` `--related` `--source` |

```bash
kb gap add "<text>" --area "<area>" --note "<where it came from>" --no-dry-run
kb gap list --state open --json
kb gap promote <id>... --to learning/<topic> --no-dry-run
kb gap close <id>... --note "[[dir/slug|Title]]" --no-dry-run
```

A **dated slug sets `created:`** on `kb article new`, so a topic article named for a date
needs no extra flag.

A gap is `open` until it joins a topic (`promoted`) or is answered (`learned`). The state
is which table it sits in; nothing else records it.
