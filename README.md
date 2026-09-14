# kb

A CLI that maintains a personal knowledge base of plain markdown.

The knowledge base is written and kept tidy by an LLM; `kb` does the bookkeeping around
it. That split is the whole design:

| Work | Who |
|---|---|
| Decide what is worth capturing | the model — judgment |
| Find whether an article already covers it | the model — semantic matching, not string matching |
| Decide update-vs-create, and which articles to touch | the model — the hard part |
| Write the prose | the model |
| Regenerate the index and the backlink graph | `kb index` — mechanical |
| Find broken links, dead pointers, stale dates, orphans | `kb lint` — mechanical |

A script cannot decide which existing article a new fact belongs to. A model
hand-maintaining an index is slow, expensive, and drifts. Neither side should do the
other's job.

## The vault

Plain markdown with YAML frontmatter and `[[wikilinks]]`, in a git repository you own.
No database, no embeddings, no server. It opens in Obsidian with no configuration, and
an agent reads it with nothing installed at all — it walks `_index.md`, opens the two or
three articles it needs, and follows their links.

```
<vault>/
  _index.md        master catalog — generated
  _backlinks.json  reverse link index — generated
  incidents/  systems/  runbooks/  guides/  learning/  research/  journal/
  reference/       pointers to documents that stay in their own repo
  raw/entries/     the source material articles were synthesized from
```

`reference/` is the part that keeps the vault from going stale. A finished document that
lives next to the code it documents **stays there** and gets a stub pointing at it.
Copying it in would produce two versions of the truth and no way to tell which one aged.

## Install

```bash
uv tool install --editable .
kb init
kb skill install --no-dry-run
```

## Commands

```bash
kb index          # rebuild _index.md and _backlinks.json from frontmatter
kb lint           # broken links, dead pointers, missing fields, orphans, stale dates
kb schema         # print the rules the vault follows
kb doctor         # check the config, the vault, and the skill link still resolve
```

Every read command takes `--json`, because the main caller is an agent rather than a
person.

## The rules

`SCHEMA.md` ships inside the package and is read by everything that writes to the vault,
so the interactive path and the batch path cannot drift into two different wikis. It is
never copied into a vault — upgrading `kb` upgrades the rules everywhere at once. Print
it with `kb schema`.

## License

MIT
