"""Sessions, cookies, and the gates on the signup ladder.

The session design follows HOSTED_PRD §5, and the one decision worth
restating is why the session is *our own opaque token in our own table*
rather than a JWT: an agent run outlives any access token, ``EventSource``
cannot send an ``Authorization`` header, and today's real bug is that auth is
checked once at connect — so a user who logs out keeps receiving live output
for the rest of an hour-long run. Only a row we can re-read closes that, and
only an opaque token keeps the identity provider swappable.

The signup ladder (§8) is a ladder because the cheap gates come first:
Turnstile and a disposable-domain check cost nothing, email verification
costs a round trip, and a card is the expensive one we do not ask for in v1.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie

from . import config, store

#: Prefixed cookies are enforced by the browser: __Host- requires Secure, a
#: Path of /, and *no* Domain attribute, which is what makes it impossible for
#: a sibling subdomain to set or overwrite it. That matters here specifically
#: because task files are served from another host (§7).
COOKIE_NAME = "__Host-opposable_session"

#: The local-mode identity. Not a backdoor: hosted mode never reaches it, and
#: `preflight` refuses to start without auth configured.
LOCAL_ORG = "local"
LOCAL_USER = "local"

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

# A starter list. The real one is a maintained feed; this is here so the gate
# exists and has somewhere to grow (OPPOSABLE_DISPOSABLE_DOMAINS extends it).
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "sharklasers.com",
    "getnada.com", "dispostable.com", "maildrop.cc", "temp-mail.org",
})


class AuthError(ValueError):
    """Registration or login was refused. The message is user-facing."""


@dataclass(frozen=True)
class Identity:
    """Who a request is acting as. ``org_id`` is the tenant boundary."""

    user_id: str
    org_id: str
    email: str = ""
    email_verified: bool = True

    @property
    def is_local(self) -> bool:
        return self.org_id == LOCAL_ORG


LOCAL_IDENTITY = Identity(user_id=LOCAL_USER, org_id=LOCAL_ORG, email="local")


# ------------------------------------------------------------------ passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ------------------------------------------------------------- signup gates


def disposable_domains() -> frozenset[str]:
    extra = os.environ.get("OPPOSABLE_DISPOSABLE_DOMAINS", "")
    return DISPOSABLE_DOMAINS | {d.strip().lower() for d in extra.split(",") if d.strip()}


def check_email(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or " " in email:
        raise AuthError("a valid email address is required")
    if domain in disposable_domains():
        raise AuthError("that email provider is not accepted")
    return email


def check_password(password: str) -> str:
    if len(password) < 12:
        raise AuthError("password must be at least 12 characters")
    return password


def check_turnstile(token: str | None, remote_ip: str | None = None) -> None:
    """Cloudflare Turnstile. Skipped entirely when no secret is configured,
    which is the local case; ``preflight`` is what stops that from being the
    hosted case too."""
    secret = os.environ.get("OPPOSABLE_TURNSTILE_SECRET", "").strip()
    if not secret:
        return
    if not token:
        raise AuthError("captcha verification is required")
    from . import egress
    from urllib.parse import urlencode

    form = {"secret": secret, "response": token}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        _url, _ctype, body = egress.fetch(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            method="POST",
            body=urlencode(form).encode("ascii"),
            content_type="application/x-www-form-urlencoded",
        )
    except Exception as exc:  # noqa: BLE001 — a failed check is a failed signup
        raise AuthError("captcha verification failed") from exc
    import json

    if not json.loads(body or "{}").get("success"):
        raise AuthError("captcha verification failed")


# ---------------------------------------------------------------- operations


def register(
    db: store.Store,
    email: str,
    password: str,
    terms_version: str | None = None,
    turnstile_token: str | None = None,
    remote_ip: str | None = None,
) -> dict:
    email = check_email(email)
    check_password(password)
    check_turnstile(turnstile_token, remote_ip)
    if config.hosted() and not terms_version:
        # Posting terms is unenforceable; acceptance has to be an affirmative
        # act recorded against a version (HOSTED_PRD §11).
        raise AuthError("the terms of service must be accepted")
    if db.user_by_email(email):
        raise AuthError("that email is already registered")
    return db.create_user(email, hash_password(password), terms_version=terms_version)


def login(db: store.Store, email: str, password: str) -> tuple[str, Identity]:
    user = db.user_by_email(check_email(email))
    if not user or not verify_password(password, user["password_hash"]):
        # One message for both cases: distinguishing them turns login into an
        # account-existence oracle.
        raise AuthError("email or password is incorrect")
    if user["suspended_at"] is not None:
        raise AuthError("this account is suspended")
    org_id = db.primary_org(user["id"])
    if not org_id:
        raise AuthError("account has no organization")
    secret = db.create_session(user["id"], org_id)
    return secret, Identity(
        user_id=user["id"],
        org_id=org_id,
        email=user["email"],
        email_verified=user["email_verified_at"] is not None,
    )


def identity_for(db: store.Store, secret: str | None) -> Identity | None:
    if not secret:
        return None
    row = db.session(secret)
    if not row:
        return None
    return Identity(
        user_id=row["user_id"],
        org_id=row["org_id"],
        email=row["email"],
        email_verified=row["email_verified_at"] is not None,
    )


# ------------------------------------------------------------------- cookies


def cookie_header(secret: str, max_age: int = store.SESSION_TTL_SECONDS) -> str:
    return (
        f"{COOKIE_NAME}={secret}; Max-Age={max_age}; Path=/; Secure; HttpOnly; "
        # Lax, not Strict: Strict drops the cookie on the OAuth callback, so
        # the login flow would loop. CSRF is covered by Sec-Fetch-Site instead.
        "SameSite=Lax"
    )


def clear_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax"


def session_from_cookies(raw: str | None) -> str | None:
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 — a malformed cookie header is just absent
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


def check_csrf(sec_fetch_site: str | None, origin: str | None, allowed_origin: str | None) -> None:
    """Primary defence is ``Sec-Fetch-Site``; ``Origin`` is the fallback.

    Sec-Fetch-Site is set by the browser and cannot be forged by page script,
    which is exactly the property a CSRF check needs.
    """
    if sec_fetch_site is not None:
        if sec_fetch_site not in ("same-origin", "none"):
            raise AuthError(f"cross-site request refused ({sec_fetch_site})")
        return
    if origin is not None and allowed_origin and origin != allowed_origin:
        raise AuthError("cross-origin request refused")
    if origin is None and allowed_origin:
        # No Sec-Fetch-Site and no Origin: an old client, or a tool. Refuse in
        # hosted mode rather than guess.
        raise AuthError("request origin could not be established")


def verification_link(base_url: str, secret: str) -> str:
    return f"{base_url.rstrip('/')}/api/auth/verify?token={secret}"


def send_verification(email: str, link: str) -> None:
    """Deliver a verification link.

    No mail provider is configured in v1, so this logs the link — usable for
    local development and honest about it. ``preflight`` refuses to start
    hosted until ``OPPOSABLE_MAIL_PROVIDER`` names a real one.
    """
    provider = os.environ.get("OPPOSABLE_MAIL_PROVIDER", "").strip()
    if not provider:
        print(f"[opposable] verification link for {email}: {link}")
        return
    raise NotImplementedError(f"mail provider {provider!r} is not implemented")


def now() -> float:
    return time.time()
