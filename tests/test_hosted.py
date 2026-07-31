"""Stage 0 ship-blockers (HOSTED_PRD §10).

These are adversarial tests: each one is a thing a hostile user with a valid
account would try. They are not "does the feature work" tests — they are the
exit criterion for opening the door, so a failure here blocks a deploy.
"""

import os
import sys
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
