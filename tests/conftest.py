"""Shared fixtures.

Every test runs against a throwaway config directory and a throwaway vault. The autouse
fixture is what guarantees no test can reach the real ~/.config/kb or the real vault.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from kb import schema

_KB_VARS = ("KB_CONFIG_DIR", "KB_VAULT", "KB_REPO_ROOT", "KB_MODEL")

ArticleWriter = Callable[..., Path]


@pytest.fixture(autouse=True)
def kb_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point kb at a temp config directory and an empty repo root.

    Both matter. Without the repo root override, anything that resolves an article's
    `repos:` field scans the real ~/workspace — which reaches outside the test, depends
    on whatever is checked out, and took the suite from one second to forty.
    """
    for var in _KB_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KB_CONFIG_DIR", str(tmp_path / "config"))
    empty_root = tmp_path / "no-repos"
    empty_root.mkdir()
    monkeypatch.setenv("KB_REPO_ROOT", str(empty_root))
    yield tmp_path / "config"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty vault with every directory SCHEMA.md defines, wired up as KB_VAULT."""
    root = tmp_path / "vault"
    for name in schema.DIRECTORIES:
        (root / name).mkdir(parents=True)
    (root / schema.RAW_DIRECTORY / "entries").mkdir(parents=True)
    monkeypatch.setenv("KB_VAULT", str(root))
    return root


@pytest.fixture
def article(vault: Path) -> ArticleWriter:
    """Write a valid article and return its path; keyword arguments override fields."""

    def write(slug: str, body: str = "Body text.\n", **fields: object) -> Path:
        frontmatter: dict[str, object] = {
            "title": slug.split("/")[-1].replace("-", " ").title(),
            "type": schema.TYPE_DIRECTORY.get(slug.split("/")[0], "concept"),
            "status": "stable",
            "created": "2026-01-01",
            "last_updated": "2026-01-02",
            "summary": f"Summary for {slug}.",
        }
        frontmatter.update(fields)
        lines = ["---"]
        for key, value in frontmatter.items():
            if value is None:
                continue
            if isinstance(value, list):
                rendered = ", ".join(f'"{item}"' if "[[" in str(item) else str(item) for item in value)
                lines.append(f"{key}: [{rendered}]")
            else:
                lines.append(f"{key}: {value}")
        lines += ["---", "", body]
        path = vault / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    return write
