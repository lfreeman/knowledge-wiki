# CLAUDE.md

Guidance for Claude Code when working in this repository.

`kb` — a CLI that maintains a personal knowledge base of plain markdown. **Read `PLAN.md`
before implementing anything**; §10 is the specification and the build order.

This repo is public and `PLAN.md` is gitignored. Never copy private names — repos, services,
tickets, customers, hosts — from `PLAN.md` or the vault into tracked files.

## Commands

```bash
uv sync                                  # install dependencies
uv run kb <command>                      # run in dev mode
uv run pytest                            # all tests
uv run ruff check src/ tests/            # lint
uv run mypy                              # type check
uv tool install --editable . --force     # install globally
```

## Architecture

**Entry point**: `src/kb/cli.py` — Typer app registering subcommand groups, holding no logic.

- `SCHEMA.md` — the rules, shipped as **package data** inside `src/kb/`. Read by everything
  that writes to the vault, so the interactive and batch paths cannot drift into two
  different wikis. **Never copied into a vault**: one copy means upgrading `kb` upgrades the
  rules everywhere at once. `kb schema` prints it.
- `schema.py` — the executable half of `SCHEMA.md`: the directory and type vocabulary, the
  frontmatter parser and renderer, the wikilink parser. When one half changes the other has
  to, and `tests/test_schema.py` asserts they still agree.
- `config.py` — settings only (`~/.config/kb`, relocatable with `KB_CONFIG_DIR`). The vault
  path lives here rather than being inferred from the working directory, because capture
  fires while you are sitting in some unrelated repository.
- `errors.py` — the user-facing error types and `run()`, the context manager commands wrap
  their body in.
- `output.py` — the shared `--json` and `--dry-run` option shapes, plus table rendering.
- `commands/` — one module per subcommand group.
- `skills/capture/SKILL.md` — the skill, symlinked into `~/.claude/skills/capture` by
  `kb skill install`. It calls the CLI and is independent of the Python package.

## The line this project is built on

Judgment belongs to the model; bookkeeping belongs to a script. A script cannot decide which
existing article a new fact belongs to. A model hand-maintaining an index is slow, expensive,
and drifts. So `index` and `lint` involve no model at all, `adopt inspect` gathers evidence
and decides nothing, and nothing in this package writes prose.

## Conventions

- Ruff: line-length 120, rules E/F/I/N/W/UP. Python 3.13+ (`X | Y` unions, `Annotated` options).
- `cli.py` holds no logic. Commands validate arguments and delegate; `errors.run()` renders the
  known user-error types as a red one-line `Error:` on stderr with exit 1, and lets anything
  unexpected bubble up with its traceback.
- Every read command takes `--json` so an agent parses structured output instead of a Rich
  table. This matters more here than in a normal CLI — Claude is the primary caller.
- Writes default to `--dry-run`, expressed as a `--dry-run/--no-dry-run` pair. `kb index` is
  the deliberate exception: it regenerates derived data, so a preview-first default would be
  friction on the most-run command.
- Tests use `typer.testing.CliRunner`. An autouse fixture points `KB_CONFIG_DIR` at a temp
  directory and the `vault` fixture points `KB_VAULT` at a throwaway vault, so no test can
  reach the real config or the real knowledge base.

## Three defects that are invisible in raw markdown

All three are about how a *consumer* resolves a file, not how it reads, which is why they
survived review and why they are now lint rules.

1. Wikilinks resolve by **filename**, not by the `title:` field. `[[Some Title]]` matches
   nothing and silently creates an empty note at the vault root when clicked.
2. Inside a markdown table an unescaped `|` is a column separator, so `[[path|Title]]` in a
   table row splits across two cells and the link is destroyed.
3. An editor that reflows a table pushes the alignment padding *inside* the wikilinks. The
   fix is to generate minimal unpadded rows, leaving nothing to reflow.

The general lesson, worth remembering for any future consumer: **some defects are only
observable through the tool that reads the file.**
