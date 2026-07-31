"""Stage 0 ship-blockers (HOSTED_PRD §10).

These are adversarial tests: each one is a thing a hostile user with a valid
account would try. They are not "does the feature work" tests — they are the
exit criterion for opening the door, so a failure here blocks a deploy.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from opposable import config
from opposable.sandbox import SANDBOX_ENV_ALLOWLIST, LocalSandbox, sandbox_env

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
        {"task": "x" * 100, "base_url": "https://api.openai.com/v1"},
    )
    assert status == 201
    status, _ = request(
        port, "POST", "/api/tasks",
        {"task": "x" * 100, "base_url": "https://api.openai.com.evil.example/v1"},
    )
    assert status == 400
    httpd.shutdown()


def test_hosted_refuses_unlisted_model_and_image(tmp_path, hosted):
    httpd, port = start_server(tmp_path, SCRIPT)
    status, body = request(port, "POST", "/api/tasks", {"task": "x" * 100, "model": "gpt-9-ultra"})
    assert status == 400 and "model" in body["error"]
    status, body = request(
        port, "POST", "/api/tasks", {"task": "x" * 100, "image": "attacker/backdoor:latest"}
    )
    assert status == 400 and "image" in body["error"]
    status, _ = request(port, "POST", "/api/tasks", {"task": "x" * 100, "model": "claude-sonnet-5"})
    assert status == 201
    httpd.shutdown()


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
