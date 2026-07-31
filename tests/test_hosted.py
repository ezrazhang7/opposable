"""Stage 0 ship-blockers (HOSTED_PRD §10).

These are adversarial tests: each one is a thing a hostile user with a valid
account would try. They are not "does the feature work" tests — they are the
exit criterion for opening the door, so a failure here blocks a deploy.
"""

import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from opposable import config
from opposable.sandbox import SANDBOX_ENV_ALLOWLIST, LocalSandbox, sandbox_env
from opposable.server import _check_params

from .test_server import SCRIPT, request, start_server

SECRETS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("OPPOSABLE_HOSTED", "1")
    return config


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
    status, body = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "https://attacker.example/v1"},
    )
    assert status == 400 and "base_url" in body["error"]
    assert httpd.manager.list() == []
    httpd.shutdown()


def test_hosted_allows_only_allowlisted_base_urls(tmp_path, hosted, monkeypatch):
    monkeypatch.setenv("OPPOSABLE_ALLOWED_BASE_URLS", "https://api.openai.com/v1")
    httpd, port = start_server(tmp_path, SCRIPT)
    status, _ = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "https://api.openai.com.evil.example/v1"},
    )
    assert status == 400
    httpd.shutdown()
    # The accepted case is asserted against the validator directly: in hosted
    # mode a create still stops at the sandbox check below, which is the point.
    _check_params({"base_url": "https://api.openai.com/v1"})


def test_hosted_refuses_unlisted_model_and_image(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100, "model": "gpt-9-ultra"})
    assert status == 400 and "model" in body["error"]
    status, body = request(
        port, "POST", "/api/tasks", {"task": "x" * 100, "image": "attacker/backdoor:latest"}
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


# ------------------------------------------------- 0b: hosted refuses dev boxes


def test_hosted_refuses_development_sandboxes(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    for kind in ("docker", "local"):
        status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100, "sandbox": kind})
        assert status == 400 and "development-only" in body["error"]
    # ...including the default, so hosted mode cannot run a task at all until
    # a microVM backend exists.
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100})
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
