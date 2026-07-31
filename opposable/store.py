"""Identity storage, stdlib ``sqlite3``.

The schema is HOSTED_PRD §6 verbatim where it applies, so Stage 2's move to
Postgres is a driver swap rather than a redesign. What is *not* here is
deliberate: tasks, events and files stay on disk until Stage 2 migrates them
wholesale, and this module is only the identity half — orgs, users,
memberships, sessions. Task ownership rides in each task's ``meta.json``,
which is exactly what the PRD's backfill step reads.

Two properties of the Postgres target that sqlite cannot give us, recorded
here so nobody assumes they are already in place:

- **No row-level security.** Postgres gets RLS as a backstop under application
  filtering; here, application filtering is the *only* layer. Every query in
  this module therefore takes ``org_id`` as a parameter rather than trusting a
  caller to have filtered already.
- **No ``citext``.** ``COLLATE NOCASE`` stands in for case-insensitive email
  and slug uniqueness.

Connections are opened per operation. ``ThreadingHTTPServer`` runs a thread
per request and sqlite connections are not thread-safe; a connection per call
against a WAL-mode database is both correct and fast enough at this size.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id          TEXT PRIMARY KEY,
    slug        TEXT UNIQUE COLLATE NOCASE NOT NULL,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id                 TEXT PRIMARY KEY,
    email              TEXT UNIQUE COLLATE NOCASE NOT NULL,
    password_hash      TEXT NOT NULL,
    email_verified_at  REAL,
    terms_version      TEXT,
    terms_accepted_at  REAL,
    suspended_at       REAL,
    suspended_reason   TEXT,
    created_at         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    org_id   TEXT NOT NULL REFERENCES orgs(id),
    user_id  TEXT NOT NULL REFERENCES users(id),
    role     TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    org_id      TEXT NOT NULL REFERENCES orgs(id),
    token_hash  BLOB UNIQUE NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    revoked_at  REAL
);

CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash  BLOB PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    expires_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions (user_id);
CREATE INDEX IF NOT EXISTS memberships_by_user ON memberships (user_id, org_id);
"""

SESSION_TTL_SECONDS = 30 * 24 * 3600
VERIFICATION_TTL_SECONDS = 24 * 3600


def token_hash(token: str) -> bytes:
    """Sessions and verification links are stored only as digests.

    A database dump must not be a set of working credentials, and a token we
    never persist is one that cannot leak from a backup.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ users

    def create_user(
        self,
        email: str,
        password_hash: str,
        org_name: str | None = None,
        terms_version: str | None = None,
    ) -> dict:
        """Create a user and the personal org they own.

        Every user gets an org even though there is no teams UI: making
        ``org_id`` the tenant boundary from day one is what stops "add teams"
        from becoming "re-authorize every endpoint" later.
        """
        now = time.time()
        user_id, org_id = uuid.uuid4().hex, uuid.uuid4().hex
        slug = f"{email.split('@')[0][:24]}-{org_id[:8]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO orgs (id, slug, name, created_at) VALUES (?, ?, ?, ?)",
                (org_id, slug, org_name or email.split("@")[0], now),
            )
            conn.execute(
                "INSERT INTO users (id, email, password_hash, terms_version,"
                " terms_accepted_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, email, password_hash, terms_version, now if terms_version else None, now),
            )
            conn.execute(
                "INSERT INTO memberships (org_id, user_id, role) VALUES (?, ?, 'owner')",
                (org_id, user_id),
            )
        return {"id": user_id, "email": email, "org_id": org_id, "created_at": now}

    def user_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def primary_org(self, user_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT org_id FROM memberships WHERE user_id = ? ORDER BY role LIMIT 1",
                (user_id,),
            ).fetchone()
        return row["org_id"] if row else None

    def org(self, org_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
        return dict(row) if row else None

    def mark_email_verified(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET email_verified_at = ? WHERE id = ?", (time.time(), user_id)
            )

    def suspend_user(self, user_id: str, reason: str) -> None:
        """Suspension revokes every session, or the account stays usable for
        as long as a stolen cookie lives."""
        with self._connect() as conn:
            now = time.time()
            conn.execute(
                "UPDATE users SET suspended_at = ?, suspended_reason = ? WHERE id = ?",
                (now, reason, user_id),
            )
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )

    # --------------------------------------------------------------- sessions

    def create_session(self, user_id: str, org_id: str, ttl: float = SESSION_TTL_SECONDS) -> str:
        """Returns the secret. It is never stored, only its digest."""
        secret = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, org_id, token_hash, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, user_id, org_id, token_hash(secret), now, now + ttl),
            )
        return secret

    def session(self, secret: str) -> dict | None:
        """Read the session **row**, every time.

        Deliberately not a JWT check: the SSE layer re-runs this on a
        heartbeat so a logout or a suspension takes effect during an
        hour-long run, which a self-contained token cannot do.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.*, u.suspended_at, u.email, u.email_verified_at"
                " FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash = ?",
                (token_hash(secret),),
            ).fetchone()
        if not row:
            return None
        if row["revoked_at"] is not None or row["expires_at"] < time.time():
            return None
        if row["suspended_at"] is not None:
            return None
        return dict(row)

    def revoke_session(self, secret: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (time.time(), token_hash(secret)),
            )

    def purge_expired(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
            conn.execute("DELETE FROM email_verifications WHERE expires_at < ?", (time.time(),))
        return cur.rowcount

    # ----------------------------------------------------- email verification

    def create_verification(self, user_id: str) -> str:
        secret = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash(secret), user_id, time.time() + VERIFICATION_TTL_SECONDS),
            )
        return secret

    def consume_verification(self, secret: str) -> str | None:
        digest = token_hash(secret)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM email_verifications WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            if not row or row["expires_at"] < time.time():
                return None
            conn.execute("DELETE FROM email_verifications WHERE token_hash = ?", (digest,))
            conn.execute(
                "UPDATE users SET email_verified_at = ? WHERE id = ?", (time.time(), row["user_id"])
            )
        return row["user_id"]
