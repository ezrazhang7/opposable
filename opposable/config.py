"""Deployment configuration: what changes between a laptop and the internet.

One switch, ``OPPOSABLE_HOSTED=1``, separates the two worlds:

- **Local** (default) — single user, server bound to 127.0.0.1, the API key is
  yours, the sandbox shares your host if you ask it to. Client-supplied
  parameters are trusted because the client *is* the operator.
- **Hosted** — strangers submit the prompts. Nothing client-supplied selects a
  destination, dev sandbox backends refuse to run, and the process fails to
  start rather than run half-secured (see :func:`preflight`).

Every value here is read from the environment at call time, not import time,
so tests and embedders can flip a switch without reloading the module.
"""

from __future__ import annotations

import os

# Models the hosted product will run. Sonnet is the default; Opus is opt-in
# because a stuck Opus loop at ~1M context burns ~$24/hour (HOSTED_PRD §8).
DEFAULT_MODEL_ALLOWLIST = (
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "claude-opus-5",
)

DEFAULT_IMAGE_ALLOWLIST = ("ubuntu:24.04",)


def hosted() -> bool:
    """True when this process serves the public internet."""
    return os.environ.get("OPPOSABLE_HOSTED", "").strip() not in ("", "0", "false", "no")


def _list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def allowed_models() -> tuple[str, ...]:
    return _list("OPPOSABLE_ALLOWED_MODELS", DEFAULT_MODEL_ALLOWLIST)


def allowed_images() -> tuple[str, ...]:
    return _list("OPPOSABLE_ALLOWED_IMAGES", DEFAULT_IMAGE_ALLOWLIST)


def allowed_base_urls() -> tuple[str, ...]:
    """Endpoints a client may name. Empty by default: in hosted mode a client
    supplying a ``base_url`` would redirect our ``Authorization`` header to a
    host of their choosing (HOSTED_PRD §2 finding 3)."""
    return _list("OPPOSABLE_ALLOWED_BASE_URLS")


class ConfigError(ValueError):
    """A client-supplied parameter is not on the allowlist."""


def check_param(name: str, value: str | None, allowed: tuple[str, ...]) -> str | None:
    """Validate one client-settable parameter.

    Locally every value is accepted — the client is the operator, spending
    their own key. In hosted mode the allowlist is the whole story, and an
    empty allowlist means the parameter is not client-settable at all.
    """
    if value in (None, ""):
        return None
    if not hosted():
        return value
    if value not in allowed:
        raise ConfigError(f"{name} {value!r} is not permitted")
    return value
