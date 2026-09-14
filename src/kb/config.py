"""Filesystem layout and configuration.

Two locations, deliberately separate. Tool settings live in one directory
(`~/.config/kb`, relocatable with `KB_CONFIG_DIR`); the content lives in the vault,
wherever the user keeps it. `SCHEMA.md` is neither — it ships inside this package and
is read from there, never copied into a vault, so upgrading `kb` upgrades the rules
everywhere at once.

Values resolve shell environment first, then `config.json`, then the defaults here.

Because the vault path comes from config rather than the working directory, `kb` works
from anywhere. That is load-bearing: capture fires while you are sitting in some
unrelated repository, never in the vault.
"""

import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .errors import ConfigError

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "kb"
DEFAULT_VAULT = Path.home() / "Documents" / "knowledge"
DEFAULT_MODEL = "sonnet"

CONFIG_FILE_NAME = "config.json"
SCHEMA_FILE_NAME = "SCHEMA.md"

#: Where Claude Code scans for skills, and the name kb installs under.
CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"
SKILL_NAME = "capture"


def schema_path() -> Path:
    """The shipped SCHEMA.md inside this package. Never copied into a vault."""
    return Path(str(files("kb") / SCHEMA_FILE_NAME))


def skill_link() -> Path:
    """The symlink Claude Code discovers, at ~/.claude/skills/capture."""
    return CLAUDE_SKILLS_DIR / SKILL_NAME


def skill_source() -> Path:
    """The repo directory the link points at. Present for an editable install."""
    return Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME


def config_dir() -> Path:
    """The directory holding config.json."""
    override = os.environ.get("KB_CONFIG_DIR")
    return Path(override).expanduser() if override else DEFAULT_CONFIG_DIR


def config_file() -> Path:
    """Path to `config.json`, which need not exist."""
    return config_dir() / CONFIG_FILE_NAME


def ensure_config_dir() -> Path:
    """Create the config directory if absent and return it."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@dataclass(frozen=True)
class Config:
    """Resolved settings for one invocation."""

    vault: Path
    model: str


def _read_config_file() -> dict[str, object]:
    path = config_file()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return loaded


def _layer(file_data: dict[str, object], key: str, env_var: str, default: str) -> str:
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env
    from_file = file_data.get(key)
    if isinstance(from_file, str) and from_file:
        return from_file
    return default


def load_config() -> Config:
    """Resolve settings from the shell environment, then `config.json`, then defaults."""
    file_data = _read_config_file()
    return Config(
        vault=Path(_layer(file_data, "vault", "KB_VAULT", str(DEFAULT_VAULT))).expanduser(),
        model=_layer(file_data, "model", "KB_MODEL", DEFAULT_MODEL),
    )
