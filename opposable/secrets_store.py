"""BYOK key storage and secret scrubbing.

v1 is bring-your-own-key (HOSTED_PRD §8). That transfers the runaway tail —
a stuck Opus loop at ~1M context burns ~$24/hour, ~$480 overnight — to the
person who caused it, and it is free KYC besides: a working provider key
means someone already passed a card-verified signup somewhere with its own
fraud stack.

Three rules about where a key may live, and this module exists to enforce
all three:

1. **Never in the primary database.** Postgres holds a *reference*; the
   value lives in a secret manager.
2. **Never in a log.** Scrubbing happens on write, not on read — a secret
   that reached the log file is already leaked.
3. **Never in a sandbox.** LLM calls go through our own process, so the
   agent never handles the key. This is also the only durable defence
   against prompt injection: the one secret an injection cannot steal is
   one the agent never sees.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

REDACTED = "[redacted]"

#: Shapes that are obviously credentials even when we have not been told
#: about them. A backstop under :func:`register_secret`, not a substitute.
_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
)

_registered: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Teach the scrubber a literal it must never emit.

    Every key this process loads passes through here, so scrubbing does not
    depend on guessing a format.
    """
    if value and len(value) >= 8:
        with _lock:
            _registered.add(value)


def scrub(text: str) -> str:
    """Redact known and probable secrets. Call on the way *into* a log."""
    if not text:
        return text
    with _lock:
        known = sorted(_registered, key=len, reverse=True)
    for value in known:
        text = text.replace(value, REDACTED)
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class SecretStore:
    """A place to put a value that must not be in the database."""

    kind = "base"

    def put(self, ref: str, value: str) -> None:
        raise NotImplementedError

    def get(self, ref: str) -> str | None:
        raise NotImplementedError

    def delete(self, ref: str) -> None:
        raise NotImplementedError


class LocalFileSecretStore(SecretStore):
    """Development only: a 0600 JSON file beside the task directories.

    This is the same trust model as the ``.env.local`` the CLI already reads,
    which is fine for one operator on their own machine and disqualifying for
    anyone else's keys. Hosted mode refuses to start on it.
    """

    kind = "local-file"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass

    def put(self, ref: str, value: str) -> None:
        data = self._read()
        data[ref] = value
        self._write(data)
        register_secret(value)

    def get(self, ref: str) -> str | None:
        value = self._read().get(ref)
        register_secret(value)
        return value

    def delete(self, ref: str) -> None:
        data = self._read()
        if data.pop(ref, None) is not None:
            self._write(data)


class EnvSecretStore(SecretStore):
    """Reads ``OPPOSABLE_SECRET_<REF>``. For deployments that inject secrets
    as environment variables from a real manager."""

    kind = "env"

    def _name(self, ref: str) -> str:
        return "OPPOSABLE_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", ref).upper()

    def put(self, ref: str, value: str) -> None:
        raise NotImplementedError("the env secret store is read-only")

    def get(self, ref: str) -> str | None:
        value = os.environ.get(self._name(ref))
        register_secret(value)
        return value

    def delete(self, ref: str) -> None:
        raise NotImplementedError("the env secret store is read-only")


def build(base_dir: str | Path) -> SecretStore:
    kind = os.environ.get("OPPOSABLE_SECRET_STORE", "").strip() or "local-file"
    if kind == "local-file":
        return LocalFileSecretStore(Path(base_dir) / ".opposable-secrets.json")
    if kind == "env":
        return EnvSecretStore()
    raise NotImplementedError(f"secret store {kind!r} is not implemented")
