"""Outbound network policy.

Two distinct paths leave this system, and they need different controls:

1. **The sandbox's own traffic** — whatever the agent runs. That cannot be
   policed from inside the sandbox (a shell command can ignore any proxy
   variable we set), so the real control is network-level: an isolated network
   whose only route out is an allowlist proxy we run. This module supplies the
   configuration; :func:`opposable.sandbox.sandbox_env` injects the proxy vars
   so well-behaved tools use it, and the network makes the badly-behaved ones
   fail rather than escape.

2. **``web_fetch``** — which, despite its name, runs in the *server* process,
   not the sandbox. It has always been able to reach ``169.254.169.254`` from
   the API host itself, which is strictly worse than a sandbox reaching it.
   :func:`fetch` is the guarded replacement.

The guard is a default-deny allowlist, not a blocklist. Blocklists lose to
novel primitives, and both 2026 CVEs in this space were denylist/allowlist
bypasses rather than anything exotic (HOSTED_PRD §8).
"""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https")

#: Mail submission. Every major cloud blocks these permanently and never lifts
#: it for free tiers; we are not going to be the open relay that does.
SMTP_PORTS = (25, 465, 587)

DEFAULT_ALLOWED_PORTS = (80, 443, 8080, 8443)

#: NAT64. Not covered by any ipaddress property, and it maps straight onto
#: IPv4 space including the metadata address.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

MAX_REDIRECTS = 5


class EgressDenied(ValueError):
    """The request was refused before a connection was made."""


def denied_cidrs() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Extra networks to refuse — our own VPC, above all. Sandboxes belong in
    a separate cloud account with no network path to the control plane, and
    this is the belt to that pair of braces."""
    raw = os.environ.get("OPPOSABLE_DENIED_CIDRS", "").strip()
    if not raw:
        return ()
    return tuple(ipaddress.ip_network(c.strip()) for c in raw.split(",") if c.strip())


def allowed_hosts() -> tuple[str, ...]:
    """Hostname suffixes ``web_fetch`` may reach. Empty means "no allowlist":
    locally that is "anything public", in hosted mode it is "nothing"."""
    raw = os.environ.get("OPPOSABLE_ALLOWED_HOSTS", "").strip()
    return tuple(h.strip().lower().lstrip(".") for h in raw.split(",") if h.strip())


def proxy_url() -> str:
    """The allowlist proxy sandboxes must egress through."""
    return os.environ.get("OPPOSABLE_EGRESS_PROXY", "").strip()


def _unwrap(addr: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Return the IPv4 address hiding inside an IPv6 one, if any.

    ``::ffff:169.254.169.254`` is the metadata service wearing a hat. So is
    ``2002:a9fe:a9fe::`` (6to4) and ``64:ff9b::a9fe:a9fe`` (NAT64).
    """
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return addr.ipv4_mapped
        if addr.sixtofour:
            return addr.sixtofour
        if addr in _NAT64:
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return None


def allowed_ports() -> tuple[int, ...] | None:
    """Ports ``web_fetch`` may reach, or ``None`` for "any but SMTP".

    Multi-tenant deployments get a tight allowlist as defence in depth
    against protocol smuggling into services that speak something other than
    HTTP. A single-operator install gets any port, because plenty of ordinary
    sites and dev servers listen on odd ones and the address check is already
    the control that matters.
    """
    raw = os.environ.get("OPPOSABLE_ALLOWED_PORTS", "").strip()
    if raw:
        return tuple(int(p.strip()) for p in raw.split(",") if p.strip())
    return None if private_addresses_allowed() else DEFAULT_ALLOWED_PORTS


def private_addresses_allowed() -> bool:
    """Whether loopback and RFC1918 are reachable.

    On a single-operator install they are, and blocking them would be
    security theatre: the agent has a shell on that host and can curl
    anything this refuses. The moment there is more than one tenant they are
    someone else's machines, and the answer flips.

    Link-local is **not** covered by this — see :func:`check_address`.
    """
    from . import config

    return not (config.hosted() or config.auth_enabled())


def check_address(ip: str, allow_private: bool | None = None) -> None:
    """Refuse anything the caller has no business reaching."""
    if allow_private is None:
        allow_private = private_addresses_allowed()
    addr = ipaddress.ip_address(ip)
    for candidate in (addr, _unwrap(addr)):
        if candidate is None:
            continue
        local = candidate.is_loopback or candidate.is_private
        # Never, on any deployment. There is no legitimate reason for an
        # agent to fetch the metadata service, and it is the single most
        # valuable thing on the network to whoever is injecting the prompt.
        # `is_reserved` is qualified because ::1 sits inside ::/8 and would
        # otherwise be unreachable even on a laptop.
        always_denied = (
            candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_unspecified
            or (candidate.is_reserved and not local)
        )
        if always_denied or (local and not allow_private):
            raise EgressDenied(f"{ip} resolves into non-public address space ({candidate})")
        for network in denied_cidrs():
            if candidate.version == network.version and candidate in network:
                raise EgressDenied(f"{ip} is inside a denied network ({network})")


def check_host(hostname: str) -> None:
    allowed = allowed_hosts()
    if not allowed:
        from . import config

        if config.hosted():
            raise EgressDenied(
                "no egress allowlist is configured; default-deny refuses every host"
            )
        return
    host = hostname.lower().rstrip(".")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in allowed):
        raise EgressDenied(f"{hostname} is not on the egress allowlist")


def resolve(hostname: str, port: int) -> list[str]:
    """Resolve, then validate **every** answer.

    Checking one address and connecting to another is the whole DNS-rebinding
    trick, so a name that resolves to a mix of public and private addresses is
    refused outright rather than partially honoured.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressDenied(f"cannot resolve {hostname}: {exc}") from exc
    addresses = []
    allow_private = private_addresses_allowed()
    for info in infos:
        ip = info[4][0]
        check_address(ip, allow_private)
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise EgressDenied(f"{hostname} resolved to nothing")
    return addresses


def check_url(url: str) -> tuple[str, str, int, str]:
    """Validate a URL end to end. Returns (scheme, host, port, path+query)."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise EgressDenied(f"scheme {parts.scheme!r} is not permitted")
    if not parts.hostname:
        raise EgressDenied("url has no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port in SMTP_PORTS:
        raise EgressDenied(f"port {port} is permanently blocked")
    allowed = allowed_ports()
    if allowed is not None and port not in allowed:
        raise EgressDenied(f"port {port} is not permitted")
    check_host(parts.hostname)
    target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    return parts.scheme, parts.hostname, port, target


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to the address we validated, not to whatever a second lookup
    returns. Without pinning, validation and connection are two separate
    resolutions and the gap between them is the vulnerability."""

    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        # server_hostname stays the name, so certificate validation is still
        # against the host the caller asked for.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(
    url: str,
    timeout: float = 30,
    max_bytes: int = 2_000_000,
    user_agent: str = "opposable/0.1",
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[str, str, str]:
    """Request a URL under egress policy. Returns (final_url, content_type, body).

    Redirects are followed manually because the whole point is to re-run the
    policy on every hop — a permitted host redirecting to ``169.254.169.254``
    is the standard bypass, and any library that follows redirects for you
    will take it.
    """
    seen = []
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, target = check_url(url)
        ip = resolve(host, port)[0]
        conn_cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        conn = conn_cls(host, ip, port, timeout)
        headers = {"User-Agent": user_agent, "Host": host}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            conn.request(method, target, body=body, headers=headers)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    raise EgressDenied(f"{resp.status} with no Location header")
                nxt = _absolutise(url, location)
                if nxt in seen:
                    raise EgressDenied("redirect loop")
                seen.append(url)
                url = nxt
                continue
            body = resp.read(max_bytes).decode("utf-8", errors="replace")
            return url, resp.headers.get("Content-Type", ""), body
        finally:
            conn.close()
    raise EgressDenied(f"more than {MAX_REDIRECTS} redirects")


def _absolutise(base: str, location: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, location)
