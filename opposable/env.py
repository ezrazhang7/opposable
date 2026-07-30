"""Dotenv loading, stdlib-only.

Reads ``.env.local`` and ``.env`` so users don't have to export API keys
in every terminal session. Precedence, highest first:

1. Real environment variables (never overwritten)
2. ``.env.local`` (personal, gitignored)
3. ``.env`` (shared defaults, may be committed)

Files are searched from the current directory upward so running
``opposable`` from a subdirectory of a project still finds its env files.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILENAMES = (".env.local", ".env")


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Supports comments, blank lines, an optional
    ``export `` prefix, and single- or double-quoted values."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            # strip trailing inline comment: KEY=value  # note
            value = value.split(" #", 1)[0].rstrip()
        result[key] = value
    return result


def load_env_files(start: str | Path | None = None) -> dict[str, str]:
    """Load env files into ``os.environ`` without overriding existing vars.

    Walks from ``start`` (default: cwd) up to the filesystem root and loads
    the first directory that contains any of ``ENV_FILENAMES``. Returns the
    variables that were actually set.
    """
    directory = Path(start or os.getcwd()).resolve()
    for candidate in (directory, *directory.parents):
        found = [candidate / name for name in ENV_FILENAMES if (candidate / name).is_file()]
        if not found:
            continue
        loaded: dict[str, str] = {}
        # ENV_FILENAMES is ordered highest-precedence first
        for path in found:
            for key, value in parse_env_file(path).items():
                if key not in os.environ and key not in loaded:
                    loaded[key] = value
        os.environ.update(loaded)
        return loaded
    return {}