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


#: Backends that share a kernel (or a whole machine) with the host. Fine for
#: the operator's own laptop, disqualifying the moment a stranger submits the
#: prompt — escaping a container means one kernel bug, escaping a microVM
#: means breaking virtualization (HOSTED_PRD §4).
DEV_SANDBOX_BACKENDS = ("local", "docker")


def auth_enabled() -> bool:
    """Hosted mode always authenticates. Locally it is opt-in, so a
    self-hoster exposing the server on a LAN can turn it on without pretending
    to be a multi-tenant deployment."""
    if hosted():
        return True
    return os.environ.get("OPPOSABLE_AUTH", "").strip() not in ("", "0", "false", "no")


def app_origin() -> str:
    """Our own origin, used as the CSRF fallback when Sec-Fetch-Site is
    absent. Empty locally, where there is no cross-origin threat model."""
    return os.environ.get("OPPOSABLE_APP_ORIGIN", "").strip().rstrip("/")


def terms_version() -> str:
    return os.environ.get("OPPOSABLE_TERMS_VERSION", "").strip()


def files_origin() -> str:
    """Where task files are served from.

    Must be a **separate registrable domain**, not a subdomain — this is why
    ``googleusercontent.com`` exists. An agent that writes ``report.html`` is
    writing a page; serving it on the app origin makes that stored XSS against
    every viewer, and a subdomain still shares cookies and enough of the
    origin's trust to matter.
    """
    return os.environ.get("OPPOSABLE_FILES_ORIGIN", "").strip().rstrip("/")


def file_signing_key() -> bytes:
    """Key for short-TTL file URLs. The files origin has no session cookie —
    it is a different site on purpose — so a signature is what authorizes it."""
    return os.environ.get("OPPOSABLE_FILE_SIGNING_KEY", "").strip().encode("utf-8")


#: How long a signed file URL lives. Long enough to click, short enough that a
#: leaked Referer is stale before anyone acts on it.
FILE_URL_TTL_SECONDS = 300


def sandbox_backend() -> str:
    """The backend hosted mode will actually run. Empty until a microVM
    vendor is chosen and ``OPPOSABLE_SANDBOX_BACKEND`` names it."""
    return os.environ.get("OPPOSABLE_SANDBOX_BACKEND", "").strip()


class ConfigError(ValueError):
    """A client-supplied parameter is not on the allowlist."""


class PreflightError(RuntimeError):
    """Hosted mode is misconfigured. Refuse to start rather than serve the
    internet with a ship-blocker unaddressed."""


def check_sandbox(kind: str) -> None:
    """Refuse a development sandbox backend in hosted mode."""
    if hosted() and kind in DEV_SANDBOX_BACKENDS:
        raise ConfigError(
            f"the {kind} sandbox is development-only; hosted mode requires a "
            f"microVM backend (set OPPOSABLE_SANDBOX_BACKEND)"
        )


def _registrable(origin: str) -> str:
    """Last two labels of a host. A deliberate approximation of the public
    suffix list — good enough to catch "I put files on a subdomain", which is
    the mistake this check exists for, and it errs toward complaining."""
    host = origin.split("//")[-1].split("/")[0].split(":")[0].lower()
    return ".".join(host.rsplit(".", 2)[-2:])


def preflight() -> list[str]:
    """Everything that must be true before this process faces the internet.

    Returns the list of problems; :func:`serve` turns a non-empty list into a
    refusal to start. Grouped by the HOSTED_PRD §10 task that owns each.
    """
    if not hosted():
        return []
    from . import egress

    problems: list[str] = []
    backend = sandbox_backend()
    if not backend:
        problems.append(
            "0b: OPPOSABLE_SANDBOX_BACKEND is unset — no microVM backend is configured"
        )
    elif backend in DEV_SANDBOX_BACKENDS:
        problems.append(f"0b: OPPOSABLE_SANDBOX_BACKEND={backend} is development-only")
    if not egress.proxy_url():
        problems.append("0b: OPPOSABLE_EGRESS_PROXY is unset — sandbox egress is unpoliced")
    if not egress.denied_cidrs():
        problems.append(
            "0b: OPPOSABLE_DENIED_CIDRS is unset — our own VPC is reachable from a sandbox"
        )
    if not app_origin():
        problems.append("0c: OPPOSABLE_APP_ORIGIN is unset — the CSRF fallback cannot work")
    if not files_origin():
        problems.append("0d: OPPOSABLE_FILES_ORIGIN is unset — user content would be served on our origin")
    elif app_origin() and _registrable(files_origin()) == _registrable(app_origin()):
        problems.append("0d: OPPOSABLE_FILES_ORIGIN shares a registrable domain with the app")
    if len(file_signing_key()) < 32:
        problems.append("0d: OPPOSABLE_FILE_SIGNING_KEY is missing or shorter than 32 bytes")
    if not terms_version():
        problems.append("0g: OPPOSABLE_TERMS_VERSION is unset — acceptance cannot be recorded")
    if not os.environ.get("OPPOSABLE_TURNSTILE_SECRET", "").strip():
        problems.append("0c: OPPOSABLE_TURNSTILE_SECRET is unset — signup has no bot gate")
    if not os.environ.get("OPPOSABLE_MAIL_PROVIDER", "").strip():
        problems.append("0c: OPPOSABLE_MAIL_PROVIDER is unset — email cannot be verified")
    return problems


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
