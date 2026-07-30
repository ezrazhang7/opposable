"""Sandboxes: where the agent's hands touch the world.

Two backends behind one interface:

- ``LocalSandbox`` — a working directory + subprocesses on the host. Fast,
  zero-dependency, appropriate when you trust the task (or are the task).
- ``DockerSandbox`` — a persistent container per task: root inside, isolated
  from the host, disposable on catastrophe. The self-hosted analogue of a
  per-task cloud VM: full control inside the box, blast radius contained
  to the box.

Both persist state for the lifetime of the task, so the filesystem can act
as the agent's externalized memory between iterations (and across resumes).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import uuid
from pathlib import Path


class Sandbox:
    """Interface. A sandbox is a place to run shells and keep files."""

    workdir: str

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        raise NotImplementedError

    def write_file(self, path: str, content: str) -> str:
        raise NotImplementedError

    def read_file(self, path: str) -> str:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class LocalSandbox(Sandbox):
    def __init__(self, root: str | None = None):
        self.root = Path(root or Path.cwd() / f".opposable-{uuid.uuid4().hex[:8]}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.workdir = str(self.root)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["bash", "-lc", command],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "OPPOSABLE_SANDBOX": "local"},
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s"

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return str(p)

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text()


class DockerSandbox(Sandbox):
    """One persistent container per task. Root inside, contained outside."""

    def __init__(self, image: str = "ubuntu:24.04", name: str | None = None):
        self.image = image
        self.name = name or f"opposable-{uuid.uuid4().hex[:8]}"
        self.workdir = "/workspace"
        self._start()

    def _start(self) -> None:
        subprocess.run(
            [
                "docker", "run", "-d", "--name", self.name,
                "--workdir", self.workdir,
                self.image, "sleep", "infinity",
            ],
            check=True,
            capture_output=True,
        )
        self._docker_exec(f"mkdir -p {self.workdir}")

    def _docker_exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["docker", "exec", self.name, "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        try:
            return self._docker_exec(command, timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s"

    def write_file(self, path: str, content: str) -> str:
        if not path.startswith("/"):
            path = f"{self.workdir}/{path}"
        quoted = shlex.quote(content)
        self._docker_exec(f"mkdir -p $(dirname {shlex.quote(path)}) && printf '%s' {quoted} > {shlex.quote(path)}")
        return path

    def read_file(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"{self.workdir}/{path}"
        code, out, err = self._docker_exec(f"cat {shlex.quote(path)}")
        if code != 0:
            raise FileNotFoundError(err.strip())
        return out

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
