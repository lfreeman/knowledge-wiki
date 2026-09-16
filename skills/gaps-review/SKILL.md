---
name: gaps-review
description: Review, cluster and prioritise the learning-gaps inbox in the kb vault, and fold clusters into topic articles. Use when the user types /gaps-review, or says "review my gaps", "what should I learn next", "organise my learning list", "clean up my gaps". Organising only — do not teach the topics here.
---

# Review the learning-gaps inbox

Gaps live in the vault as `learning/learning-gaps` and are managed with `kb gap`. Never
hand-edit that file. **Organise and prioritise only — do not teach the topics here.**

**Every write is a preview until `--no-dry-run`.**

---

## Flow

**1. Read the inbox.**

```bash
kb gap list --json          # every gap, with a count per area
kb gap list --state open --json
```

**2. Drop what is already answered.** For each area with several gaps, run
`kb search <terms> --json`. The vault has grown; some open gaps are answered by articles
written since they were logged. Close those rather than carrying them:

```bash
kb gap close g-0031 --note "[[guides/s3-streaming|AWS S3 Streaming]] §6.1" --no-dry-run
```

**3. Merge near-duplicates.** Close the later one with a note naming the id that survives.
Ids are stable, so always refer to them by id.

**4. Cluster, and do it by subject rather than by the area string.** The area field is a
label the capture step guessed; the cluster is what the gaps are actually about. Areas
written as `Networking`, `Kubernetes networking`, `AWS + k8s networking` and
`AWS S3 / networking` are one subject. Report clusters, with counts, largest first.

**5. Prioritise — three to five, with one line each.** Rank by:
- **recurrence** — how many gaps, and whether they arrived across separate days. A subject
  returned to over weeks is a real one; a burst in one afternoon may not be.
- **foundational-ness** — does understanding it unblock other gaps in the list?
- **proximity to real work** — does the user operate this thing? A subject whose failures
  already cost them time retains itself.

**6. Fold a cluster into a topic.** Three or four gaps on one subject is enough.

A **topic is one article** under `learning/`, `status: active`. It begins as a list of what
is not understood and grows as answers arrive; if it earns ordered steps and a progress log
later, those go in **the same file**. No second document, no migration. Creating a heavy
plan up front is exactly why nothing was ever promoted before.

```bash
kb article new learning/<topic> --title "<Topic> — Topic" --status active \
  --summary "..." --body-file /tmp/body.md \
  --related "[[learning/learning-gaps|Learning Gaps]]" --no-dry-run
kb gap promote g-0012 g-0019 g-0031 --to learning/<topic> --no-dry-run
```

Give the article a **Covers** line naming the areas it owns, so later gaps route to it.
Build it around something the user actually operates — a chain they debug weekly beats a
syllabus, because its failures already cost them time.

**7. Check the existing topics.** `kb search --json` for each existing `learning/` article's
Covers areas, and route matching open gaps into them before proposing anything new.

---

## What not to do

- **Do not teach.** This skill organises. If the user wants to learn one of these, that is
  a separate session against the topic article.
- **Do not create a topic for a single gap.** One gap is a note, not a subject.
- **Do not invent a new area to make a cluster look bigger.** If the gaps do not belong
  together, say so.
- **Do not close a gap the user has not agreed is answered.** Closing is a claim that they
  now know it.

End with: `Top next: <1-3 subjects>. Want me to fold any of these into a topic?`
