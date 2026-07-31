"""Stage 0 ship-blockers (HOSTED_PRD §10).

These are adversarial tests: each one is a thing a hostile user with a valid
account would try. They are not "does the feature work" tests — they are the
exit criterion for opening the door, so a failure here blocks a deploy.
"""

import http.client
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from opposable import auth, config, egress
from opposable.providers import ToolCall
from opposable.sandbox import SANDBOX_ENV_ALLOWLIST, LocalSandbox, sandbox_env
from opposable.server import _check_params

from .test_server import SCRIPT, request, start_server, turn

SECRETS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("OPPOSABLE_HOSTED", "1")
    monkeypatch.setenv("OPPOSABLE_TERMS_VERSION", "2026-07-31")
    return config


PASSWORD = "correct-horse-battery-staple"


def sign_up(port, email, password=PASSWORD, store=None):
    """Register, log in, and return request headers carrying that session.

    Pass ``store`` to skip the email gate for tests that are about something
    else; the gate itself has its own test.
    """
    status, body = request(
        port, "POST", "/api/auth/register",
        {"email": email, "password": password, "accept_terms": True},
        headers=SAME_ORIGIN,
    )
    assert status == 201, body
    if store is not None:
        store.mark_email_verified(store.user_by_email(email)["id"])
    secret = _cookie_value(port, email, password)
    return {**SAME_ORIGIN, "Cookie": f"{auth.COOKIE_NAME}={secret}"}


def _cookie_value(port, email, password):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(
        "POST", "/api/auth/login",
        body=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json", **SAME_ORIGIN},
    )
    resp = conn.getresponse()
    resp.read()
    cookie = resp.getheader("Set-Cookie") or ""
    conn.close()
    value = cookie.split(";")[0]
    assert value.startswith(auth.COOKIE_NAME + "="), cookie
    return value.split("=", 1)[1]


#: Browsers set this and page script cannot forge it, which is the property a
#: CSRF check needs. The test client has to send it like a browser would.
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


# --------------------------------------------------------------- 0a: env leak


@pytest.mark.parametrize("name", SECRETS)
def test_sandbox_shell_cannot_read_platform_keys(tmp_path, monkeypatch, name):
    """`echo $ANTHROPIC_API_KEY` was a working exfiltration primitive."""
    monkeypatch.setenv(name, "sk-platform-secret-do-not-leak")
    sandbox = LocalSandbox(root=tmp_path / "ws")
    code, out, err = sandbox.exec(f"echo \"[${name}]\"")
    assert code == 0, err
    assert "sk-platform-secret-do-not-leak" not in out
    assert out.strip() == "[]"


def test_sandbox_env_is_an_allowlist(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("OPPOSABLE_SESSION_SECRET", "session-secret")
    env = sandbox_env("local")
    assert set(env) - {"OPPOSABLE_SANDBOX"} <= set(SANDBOX_ENV_ALLOWLIST) | _platform_extras()
    assert "sk-secret" not in "".join(env.values())
    assert "aws-secret" not in "".join(env.values())
    assert "session-secret" not in "".join(env.values())


def _platform_extras() -> set[str]:
    from opposable.sandbox import _WINDOWS_ENV_ALLOWLIST

    return set(_WINDOWS_ENV_ALLOWLIST) if os.name == "nt" else set()


# ------------------------------------------------------- 0a: parameter passthrough


def test_hosted_refuses_a_client_supplied_base_url(tmp_path, hosted):
    """Pointing base_url at your own server made our Authorization header
    arrive at a host you control."""
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "byok@example.com", store=httpd.manager.store)
    status, body = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "https://attacker.example/v1"},
        headers=headers,
    )
    assert status == 400 and "base_url" in body["error"]
    assert httpd.manager.list() == []
    httpd.shutdown()


def test_hosted_allows_only_allowlisted_base_urls(tmp_path, hosted, monkeypatch):
    monkeypatch.setenv("OPPOSABLE_ALLOWED_BASE_URLS", "https://api.openai.com/v1")
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "byok2@example.com", store=httpd.manager.store)
    status, _ = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "https://api.openai.com.evil.example/v1"},
        headers=headers,
    )
    assert status == 400
    httpd.shutdown()
    # The accepted case is asserted against the validator directly: in hosted
    # mode a create still stops at the sandbox check below, which is the point.
    _check_params({"base_url": "https://api.openai.com/v1"})


def test_hosted_refuses_unlisted_model_and_image(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "models@example.com", store=httpd.manager.store)
    status, body = request(
        port, "POST", "/api/tasks", {"task": "x" * 100, "model": "gpt-9-ultra"}, headers=headers
    )
    assert status == 400 and "model" in body["error"]
    status, body = request(
        port, "POST", "/api/tasks", {"task": "x" * 100, "image": "attacker/backdoor:latest"},
        headers=headers,
    )
    assert status == 400 and "image" in body["error"]
    httpd.shutdown()
    _check_params({"model": "claude-sonnet-5", "image": "ubuntu:24.04"})


# ------------------------------------------------------- 0b: sandbox confinement


def test_absolute_paths_land_inside_the_sandbox(tmp_path):
    """A model writing /sandbox/report.md used to create C:\\sandbox\\report.md
    on the host — outside the sandbox root entirely."""
    root = tmp_path / "ws"
    sandbox = LocalSandbox(root=root)
    # Unique, because the old behaviour left real files at the drive root and
    # a fixed name would assert against someone else's litter.
    escapee = f"/sandbox/{uuid.uuid4().hex}.md"
    written = sandbox.write_file(escapee, "hello")
    assert Path(written).resolve().is_relative_to(root.resolve())
    assert sandbox.read_file(escapee) == "hello"
    assert not (Path(root.anchor) / escapee.lstrip("/")).exists()


def test_traversal_out_of_the_sandbox_is_refused(tmp_path):
    sandbox = LocalSandbox(root=tmp_path / "ws")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox.read_file("../outside.txt")
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox.write_file("../../pwned.txt", "x")


def test_symlink_out_of_the_sandbox_is_refused(tmp_path):
    """Resolution follows links, so one planted inside cannot point out."""
    root = tmp_path / "ws"
    sandbox = LocalSandbox(root=root)
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(tmp_path / "outside.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox.read_file("link.txt")


def test_tool_errors_keep_the_wrong_stuff_in(tmp_path):
    """A refused path surfaces to the model as an observation, not a crash —
    principle 5 still holds for the new boundary."""
    from opposable.tools import ToolRuntime

    runtime = ToolRuntime(LocalSandbox(root=tmp_path / "ws"))
    observation, done = runtime.execute("file_read", {"path": "../../etc/passwd"})
    assert not done and "TOOL ERROR" in observation and "escapes the sandbox" in observation


# --------------------------------------------------------- 0b: lifecycle seam


def test_archive_round_trips_the_workdir(tmp_path):
    src = LocalSandbox(root=tmp_path / "a")
    src.write_file("report.md", "findings")
    src.write_file("nested/data.json", "{}")
    archive = src.archive(tmp_path / "archives" / "task.tar.gz")

    dst = LocalSandbox(root=tmp_path / "b")
    dst.restore(archive)
    assert dst.read_file("report.md") == "findings"
    assert dst.read_file("nested/data.json") == "{}"


def test_archive_skips_reconstructible_directories(tmp_path):
    """node_modules and friends are 10-100x the archive and rebuildable."""
    sandbox = LocalSandbox(root=tmp_path / "ws")
    sandbox.write_file("keep.txt", "yes")
    sandbox.write_file("node_modules/left-pad/index.js", "x" * 5000)
    sandbox.write_file(".venv/lib/site-packages/thing.py", "y" * 5000)
    sandbox.write_file("src/__pycache__/mod.cpython-314.pyc", "z" * 5000)
    archive = sandbox.archive(tmp_path / "task.tar.gz")

    import tarfile

    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "keep.txt" in names
    assert not [n for n in names if "node_modules" in n or ".venv" in n or "__pycache__" in n]


def test_manifest_describes_the_box(tmp_path):
    sandbox = LocalSandbox(root=tmp_path / "ws")
    assert sandbox.manifest()["kind"] == "local"
    assert sandbox.snapshot() is None, "no native fast path must report None, not lie"


def test_task_records_an_immutable_manifest(tmp_path):
    httpd, port = start_server(tmp_path, SCRIPT)
    _, meta = request(port, "POST", "/api/tasks", {"task": "x" * 100})
    manifest = json.loads(
        (tmp_path / f".opposable-{meta['id']}" / ".opposable" / "state" / "manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["kind"] == "local" and "created" in manifest
    httpd.shutdown()


# -------------------------------------------------- 0c: identity and ownership


@pytest.fixture
def multi_user(monkeypatch):
    """Auth on, but not hosted — the self-hoster-on-a-LAN case, which is the
    only way to exercise tenant isolation while a runnable sandbox exists."""
    monkeypatch.setenv("OPPOSABLE_AUTH", "1")
    monkeypatch.setenv("OPPOSABLE_TERMS_VERSION", "2026-07-31")


def test_api_requires_authentication(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    for method, path in [
        ("GET", "/api/tasks"),
        ("GET", "/api/tasks/abcdef12"),
        ("POST", "/api/tasks"),
    ]:
        status, _ = request(port, method, path, {} if method == "POST" else None, SAME_ORIGIN)
        assert status == 401, f"{method} {path}"
    httpd.shutdown()


def test_another_tenants_task_is_404_never_403(tmp_path, multi_user):
    """A 403 confirms the id exists and turns a blind scan into an oracle."""
    httpd, port = start_server(tmp_path, SCRIPT)
    alice = sign_up(port, "alice@example.com")
    mallory = sign_up(port, "mallory@example.com")

    status, meta = request(port, "POST", "/api/tasks", {"task": "x" * 100}, alice)
    assert status == 201
    task_id = meta["id"]

    for method, path, body in [
        ("GET", f"/api/tasks/{task_id}", None),
        ("GET", f"/api/tasks/{task_id}/files", None),
        ("GET", f"/api/tasks/{task_id}/files/report.md", None),
        ("POST", f"/api/tasks/{task_id}/stop", {}),
        ("POST", f"/api/tasks/{task_id}/messages", {"text": "hi"}),
        ("POST", f"/api/tasks/{task_id}/resume", {}),
    ]:
        status, body_out = request(port, method, path, body, mallory)
        assert status == 404, f"{method} {path} -> {status}"
        assert "no such task" in body_out.get("error", ""), "the message must not differ either"

    # ...and it is invisible in the listing
    _, listing = request(port, "GET", "/api/tasks", None, mallory)
    assert listing == []
    _, listing = request(port, "GET", "/api/tasks", None, alice)
    assert [t["id"] for t in listing] == [task_id]
    httpd.shutdown()


def test_task_ids_are_full_uuid4(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "ids@example.com")
    _, meta = request(port, "POST", "/api/tasks", {"task": "x" * 100}, headers)
    assert len(meta["id"]) == 32, "8 hex chars is 32 bits: enumerable, and collides at ~65k tasks"
    int(meta["id"], 16)
    httpd.shutdown()


def test_legacy_eight_hex_ids_still_resolve(tmp_path, multi_user):
    """Old URLs must not 404. The directory name is the mapping."""
    legacy = tmp_path / ".opposable-ab12cd34" / ".opposable" / "state"
    legacy.mkdir(parents=True)
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "legacy@example.com")
    org_id = request(port, "GET", "/api/auth/me", None, headers)[1]["org_id"]
    (legacy / "meta.json").write_text(
        json.dumps({"task": "old task", "created": 1.0, "status": "complete", "org_id": org_id}),
        encoding="utf-8",
    )
    status, detail = request(port, "GET", "/api/tasks/ab12cd34", None, headers)
    assert status == 200 and detail["task"] == "old task"
    httpd.shutdown()


def test_task_id_cannot_traverse_out_of_the_base_directory(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "traverse@example.com")
    for bad in ("../../etc", "..%2f..%2fetc", "a" * 200, "not-hex"):
        status, _ = request(port, "GET", f"/api/tasks/{bad}", None, headers)
        assert status == 404
    httpd.shutdown()


def test_mutating_requests_need_a_same_origin_signal(tmp_path, multi_user, monkeypatch):
    monkeypatch.setenv("OPPOSABLE_APP_ORIGIN", "https://opposable.example")
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "csrf@example.com")
    cookie = {"Cookie": headers["Cookie"]}

    status, body = request(
        port, "POST", "/api/tasks", {"task": "x" * 100},
        {**cookie, "Sec-Fetch-Site": "cross-site"},
    )
    assert status == 403 and "cross-site" in body["error"]
    # No Sec-Fetch-Site and no Origin is refused too, rather than guessed at
    status, _ = request(port, "POST", "/api/tasks", {"task": "x" * 100}, cookie)
    assert status == 403
    status, _ = request(
        port, "POST", "/api/tasks", {"task": "x" * 100},
        {**cookie, "Origin": "https://opposable.example"},
    )
    assert status == 201
    httpd.shutdown()


def test_session_cookie_carries_the_right_attributes(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    request(
        port, "POST", "/api/auth/register",
        {"email": "cookie@example.com", "password": PASSWORD, "accept_terms": True},
        SAME_ORIGIN,
    )
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(
        "POST", "/api/auth/login",
        body=json.dumps({"email": "cookie@example.com", "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json", **SAME_ORIGIN},
    )
    resp = conn.getresponse()
    resp.read()
    cookie = resp.getheader("Set-Cookie")
    conn.close()
    assert cookie.startswith("__Host-")
    for attribute in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
        assert attribute in cookie
    # __Host- is only enforceable if there is no Domain attribute
    assert "Domain=" not in cookie
    httpd.shutdown()


def test_logout_revokes_the_session_immediately(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "logout@example.com")
    assert request(port, "GET", "/api/auth/me", None, headers)[0] == 200
    assert request(port, "POST", "/api/auth/logout", {}, headers)[0] == 200
    assert request(port, "GET", "/api/auth/me", None, headers)[0] == 401
    httpd.shutdown()


def test_suspension_revokes_every_session(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "suspended@example.com")
    user = httpd.manager.store.user_by_email("suspended@example.com")
    httpd.manager.store.suspend_user(user["id"], "abuse")
    assert request(port, "GET", "/api/auth/me", None, headers)[0] == 401
    httpd.shutdown()


def test_sse_closes_when_the_session_is_revoked_mid_stream(tmp_path, multi_user, monkeypatch):
    """Today auth is checked once at connect, so a logged-out user keeps
    receiving live output for the rest of an hour-long run."""
    from opposable.server import Handler

    monkeypatch.setattr(Handler, "HEARTBEAT_SECONDS", 0.2)
    monkeypatch.setattr(Handler, "REAUTH_EVERY_PINGS", 1)
    many = [
        turn(ToolCall(f"t{i}", "shell_exec", {"command": "echo tick"})) for i in range(200)
    ]
    httpd, port = start_server(tmp_path, many, slow=True)
    headers = sign_up(port, "revoked@example.com")
    _, meta = request(port, "POST", "/api/tasks", {"task": "x" * 200}, headers)

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", f"/api/tasks/{meta['id']}/events", headers=headers)
    resp = conn.getresponse()
    resp.readline()  # at least one line proves the stream is live
    request(port, "POST", "/api/auth/logout", {}, headers)

    deadline = time.time() + 20
    saw = ""
    while time.time() < deadline:
        line = resp.readline().decode("utf-8")
        if not line:
            break
        if line.startswith("event: auth_expired"):
            saw = line
            break
    conn.close()
    request(port, "POST", f"/api/tasks/{meta['id']}/stop", {}, headers)
    httpd.shutdown()
    assert saw, "a revoked session must be told, not silently dropped"


def test_credentials_are_never_stored_in_the_clear(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "hashes@example.com")
    raw = (tmp_path / ".opposable-identity.db").read_bytes()
    assert PASSWORD.encode() not in raw
    secret = headers["Cookie"].split("=", 1)[1]
    assert secret.encode() not in raw, "sessions are stored as sha256, never as the secret"
    httpd.shutdown()


def test_signup_gates(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)

    def register(email, password=PASSWORD, **extra):
        return request(
            port, "POST", "/api/auth/register",
            {"email": email, "password": password, "accept_terms": True, **extra},
            SAME_ORIGIN,
        )

    assert register("someone@mailinator.com")[0] == 400
    assert register("someone@example.com", password="short")[0] == 400
    assert register("nobody-at-all")[0] == 400
    assert register("dupe@example.com")[0] == 201
    assert register("dupe@example.com")[0] == 400
    httpd.shutdown()


def test_login_is_not_an_account_existence_oracle(tmp_path, multi_user):
    httpd, port = start_server(tmp_path, SCRIPT)
    sign_up(port, "real@example.com")
    _, wrong_password = request(
        port, "POST", "/api/auth/login", {"email": "real@example.com", "password": "nope-nope-nope"},
        SAME_ORIGIN,
    )
    _, no_such_user = request(
        port, "POST", "/api/auth/login", {"email": "ghost@example.com", "password": "nope-nope-nope"},
        SAME_ORIGIN,
    )
    assert wrong_password == no_such_user
    httpd.shutdown()


def test_hosted_requires_a_verified_email_before_running_tasks(tmp_path, hosted, monkeypatch):
    monkeypatch.setenv("OPPOSABLE_SANDBOX_BACKEND", "microvm")
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "unverified@example.com")
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100}, headers)
    assert status == 403 and "verify your email" in body["error"]

    store = httpd.manager.store
    user = store.user_by_email("unverified@example.com")
    token = store.create_verification(user["id"])
    assert request(port, "GET", f"/api/auth/verify?token={token}", None, headers)[0] == 200
    # the sandbox backend is a stub name, so this gets past auth and fails
    # later -- what matters is that it is no longer the email gate
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100}, headers)
    assert status != 403
    httpd.shutdown()


def test_registration_records_terms_acceptance(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    sign_up(port, "terms@example.com")
    user = httpd.manager.store.user_by_email("terms@example.com")
    assert user["terms_version"] == "2026-07-31" and user["terms_accepted_at"]
    httpd.shutdown()


def test_hosted_registration_requires_affirmative_acceptance(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    status, body = request(
        port, "POST", "/api/auth/register",
        {"email": "noterms@example.com", "password": PASSWORD},
        SAME_ORIGIN,
    )
    assert status == 400 and "terms of service" in body["error"]
    httpd.shutdown()


# ------------------------------------------------------------------ 0b: egress


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",      # the metadata service itself
        "::ffff:169.254.169.254",  # ...wearing an IPv6 hat
        "2002:a9fe:a9fe::",     # ...via 6to4
        "64:ff9b::a9fe:a9fe",   # ...via NAT64
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "172.16.4.4",
        "192.168.1.1",
        "fd00::1",              # IPv6 unique-local
        "0.0.0.0",
    ],
)
def test_non_public_addresses_are_refused(ip):
    with pytest.raises(egress.EgressDenied):
        egress.check_address(ip)


def test_public_addresses_pass():
    for ip in ("1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"):
        egress.check_address(ip)


def test_our_own_network_is_refused(monkeypatch):
    """Sandboxes belong in a separate cloud account; this is the belt to that
    pair of braces. Uses public space on purpose — a documentation range would
    already be caught as non-public and prove nothing."""
    monkeypatch.setenv("OPPOSABLE_DENIED_CIDRS", "8.8.8.0/24")
    with pytest.raises(egress.EgressDenied, match="denied network"):
        egress.check_address("8.8.8.8")
    egress.check_address("1.1.1.1")


def test_smtp_and_odd_ports_are_refused():
    for port in (25, 465, 587):
        with pytest.raises(egress.EgressDenied, match="permanently blocked"):
            egress.check_url(f"http://example.com:{port}/")
    with pytest.raises(egress.EgressDenied, match="not permitted"):
        egress.check_url("http://example.com:6379/")


def test_non_http_schemes_are_refused():
    for url in ("file:///etc/passwd", "gopher://example.com/", "ftp://example.com/x"):
        with pytest.raises(egress.EgressDenied, match="scheme"):
            egress.check_url(url)


def test_hosted_default_denies_every_host(hosted):
    with pytest.raises(egress.EgressDenied, match="default-deny"):
        egress.check_host("example.com")


def test_allowlist_matches_on_label_boundaries(monkeypatch):
    monkeypatch.setenv("OPPOSABLE_ALLOWED_HOSTS", "example.com")
    egress.check_host("example.com")
    egress.check_host("docs.example.com")
    # the classic bypass: a suffix that is not a subdomain
    with pytest.raises(egress.EgressDenied):
        egress.check_host("notexample.com")
    with pytest.raises(egress.EgressDenied):
        egress.check_host("example.com.evil.test")


def test_rebinding_answer_set_is_refused_wholesale(monkeypatch):
    """A name resolving to one public and one private address is refused, not
    partly honoured — checking one answer and connecting to another is the
    entire rebinding trick."""
    def fake_getaddrinfo(host, port, **kw):
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("169.254.169.254", port)),
        ]

    monkeypatch.setattr(egress.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(egress.EgressDenied, match="non-public"):
        egress.resolve("rebind.test", 80)


def test_web_fetch_refuses_the_metadata_service(tmp_path):
    """The tool runs in the server process, so this was reachable from the
    API host — worse than a sandbox reaching it."""
    from opposable.tools import ToolRuntime

    runtime = ToolRuntime(LocalSandbox(root=tmp_path / "ws"))
    observation, _ = runtime.execute(
        "web_fetch", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "TOOL ERROR" in observation and "non-public" in observation


def test_web_fetch_refuses_file_scheme(tmp_path):
    from opposable.tools import ToolRuntime

    runtime = ToolRuntime(LocalSandbox(root=tmp_path / "ws"))
    observation, _ = runtime.execute("web_fetch", {"url": "file:///etc/passwd"})
    assert "TOOL ERROR" in observation and "scheme" in observation


def test_redirects_are_revalidated(monkeypatch):
    """A permitted host redirecting to the metadata service is the standard
    bypass, and every library that follows redirects for you takes it."""
    hops = []

    class FakeResponse:
        status = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        def read(self, n):  # pragma: no cover - never reached
            return b""

    class FakeConn:
        def __init__(self, host, ip, port, timeout):
            hops.append(host)

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    def fake_getaddrinfo(host, port, **kw):
        # example.com is public; anything else (the redirect target) resolves
        # to itself, so the real address check still runs on the second hop.
        ip = "93.184.216.34" if host == "example.com" else host
        return [(2, 1, 6, "", (ip, port))]

    monkeypatch.setattr(egress, "_PinnedHTTPConnection", FakeConn)
    monkeypatch.setattr(egress.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(egress.EgressDenied, match="non-public"):
        egress.fetch("http://example.com/start")
    assert hops == ["example.com"], "the redirect target was never connected to"


def test_sandbox_env_carries_the_proxy(monkeypatch):
    monkeypatch.setenv("OPPOSABLE_EGRESS_PROXY", "http://proxy.internal:3128")
    env = sandbox_env("local")
    assert env["https_proxy"] == "http://proxy.internal:3128"
    assert env["HTTPS_PROXY"] == "http://proxy.internal:3128"


# ------------------------------------------------- 0b: hosted refuses dev boxes


def test_hosted_refuses_development_sandboxes(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    headers = sign_up(port, "boxes@example.com", store=httpd.manager.store)
    for kind in ("docker", "local"):
        status, body = request(
            port, "POST", "/api/tasks", {"task": "x" * 100, "sandbox": kind}, headers=headers
        )
        assert status == 400 and "development-only" in body["error"]
    # ...including the default, so hosted mode cannot run a task at all until
    # a microVM backend exists.
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100}, headers=headers)
    assert status == 400 and "development-only" in body["error"]
    httpd.shutdown()


def test_hosted_preflight_refuses_to_start_unconfigured(hosted, monkeypatch):
    from opposable.server import serve

    problems = config.preflight()
    assert any("OPPOSABLE_SANDBOX_BACKEND" in p for p in problems)
    with pytest.raises(config.PreflightError, match="refusing to start"):
        serve(port=0)

    monkeypatch.setenv("OPPOSABLE_SANDBOX_BACKEND", "local")
    assert any("development-only" in p for p in config.preflight())


def test_local_preflight_is_silent():
    assert config.preflight() == []


def test_local_mode_still_trusts_its_operator(tmp_path):
    """A laptop user pointing at their own Ollama is not an attacker."""
    assert not config.hosted()
    httpd, port = start_server(tmp_path, SCRIPT)
    status, _ = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "http://localhost:11434/v1", "model": "qwen2.5-coder"},
    )
    assert status == 201
    httpd.shutdown()
