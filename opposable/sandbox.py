"""Sandboxes: where the agent's hands touch the world.

Two backends behind one interface:

- ``LocalSandbox`` — a working directory + subprocesses on the host. Fast,
  zero-dependency, appropriate when you trust the task (or are the task).
- ``DockerSandbox`` — a persistent container per task, resource-capped and
  disposable on catastrophe. The self-hosted analogue of a per-task cloud VM:
  control inside the box, blast radius contained to the box.

Both persist state for the lifetime of the task, so the filesystem can act
as the agent's externalized memory between iterations (and across resumes).

**Neither is safe for strangers.** A container shares one kernel with every
other tenant; a local sandbox shares everything. Public hosting runs a microVM
backend behind this same interface, and refuses to start on these two.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path


# Everything a sandbox is allowed to inherit from the host. An allowlist, not
# a blocklist: `{**os.environ}` handed every task the platform's API keys, so
# `echo $ANTHROPIC_API_KEY` was a working exfiltration primitive.
SANDBOX_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "TERM")

# Windows needs these for a subprocess to start at all (Git Bash resolves its
# own root from SYSTEMROOT/COMSPEC). They are paths, not credentials.
_WINDOWS_ENV_ALLOWLIST = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
)


def sandbox_env(kind: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a sandbox's environment from the allowlist and nothing else."""
    names = SANDBOX_ENV_ALLOWLIST
    if os.name == "nt":
        names += _WINDOWS_ENV_ALLOWLIST
    env = {name: os.environ[name] for name in names if name in os.environ}
    env["OPPOSABLE_SANDBOX"] = kind
    if extra:
        env.update(extra)
    return env


@lru_cache(maxsize=1)
def _bash_path() -> str:
    """Locate bash, including Git Bash on Windows hosts where it isn't on PATH."""
    found = shutil.which("bash")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return "bash"


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
        """Map a model-supplied path into the sandbox, or refuse it.

        Absolute paths are reinterpreted as root-relative: a model writing
        ``/sandbox/report.md`` means its own root, not the host's ``C:\\sandbox``
        — which is where that used to land. Everything is then resolved
        (following symlinks, so a link planted inside the sandbox cannot point
        out of it) and checked against the root.
        """
        root = self.root.resolve()
        raw = Path(path)
        parts = raw.parts
        if raw.anchor:
            # Drop the anchor ('/', '\\', or 'C:\\'). Note that on Windows
            # "/sandbox" is *not* is_absolute() — it has a root but no drive —
            # and `root / "/sandbox"` silently rebases onto the drive root,
            # which is how writes escaped in the first place.
            parts = parts[1:]
        target = (root.joinpath(*parts) if parts else root).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"path escapes the sandbox: {path}")
        return target

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                [_bash_path(), "-lc", command],
                cwd=self.root,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=sandbox_env("local"),
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s"

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return str(p)

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")


#: Resource ceilings from HOSTED_PRD §4 — values, not vibes. ``memory-swap``
#: equal to ``memory`` is how Docker spells "swap disabled".
DOCKER_LIMITS = (
    "--pids-limit=512",
    "--memory=4g",
    "--memory-swap=4g",
    "--cpus=2",
)


class DockerSandbox(Sandbox):
    """One persistent container per task, contained from the host.

    Two profiles, because hardening and the product's headline capability
    genuinely conflict:

    - ``hardened`` (default) — the full HOSTED_PRD §4 flag set: every
      capability dropped, no privilege escalation, unprivileged uid, read-only
      root filesystem. **``apt-get install`` cannot work under it** — package
      installation needs root and a writable ``/``.
    - ``permissive`` — root inside a writable container, keeping the resource
      ceilings, ``no-new-privileges`` and the network isolation. This is what
      the README's "install ffmpeg and transcode" example needs.

    Neither is a multi-tenant boundary: a container shares one kernel with
    every other tenant. Hosted deployments run a microVM instead and refuse to
    start on this backend at all (see :func:`opposable.config.preflight`).
    """

    PROFILES = ("hardened", "permissive")

    def __init__(
        self,
        image: str = "ubuntu:24.04",
        name: str | None = None,
        profile: str | None = None,
        network: str | None = None,
    ):
        self.image = image
        self.name = name or f"opposable-{uuid.uuid4().hex[:8]}"
        self.volume = f"{self.name}-workspace"
        self.workdir = "/workspace"
        self.profile = profile or os.environ.get("OPPOSABLE_DOCKER_PROFILE", "hardened")
        if self.profile not in self.PROFILES:
            raise ValueError(f"unknown docker profile {self.profile!r}")
        # Self-hosters should point this at a network whose egress goes through
        # an allowlist proxy; unset means Docker's default bridge.
        self.network = network or os.environ.get("OPPOSABLE_DOCKER_NETWORK", "")
        self._start()

    def _run_flags(self) -> list[str]:
        flags = [
            "--security-opt", "no-new-privileges:true",
            *DOCKER_LIMITS,
            # A volume, not the container filesystem: it survives a restart,
            # and it is the thing snapshot()/archive() capture.
            "-v", f"{self.volume}:{self.workdir}",
            "--workdir", self.workdir,
        ]
        if self.network:
            flags += ["--network", self.network]
        # overlay2 — the default driver almost everywhere — silently rejects
        # per-container size limits, so this is opt-in rather than a default
        # that makes `docker run` fail on most hosts.
        size = os.environ.get("OPPOSABLE_DOCKER_STORAGE_SIZE", "")
        if size:
            flags += ["--storage-opt", f"size={size}"]
        if self.profile == "hardened":
            flags += [
                "--cap-drop=ALL",
                "--read-only",
                "--tmpfs", "/tmp:size=1g",
                "--user", "1000:1000",
            ]
        return flags

    def _start(self) -> None:
        if self.profile == "hardened":
            # The volume is created root-owned; the container cannot chown it
            # from inside once it is unprivileged and read-only.
            subprocess.run(
                [
                    "docker", "run", "--rm", "-v", f"{self.volume}:{self.workdir}",
                    self.image, "chown", "1000:1000", self.workdir,
                ],
                check=True,
                capture_output=True,
            )
        subprocess.run(
            [
                "docker", "run", "-d", "--name", self.name,
                *self._run_flags(),
                "--env", "OPPOSABLE_SANDBOX=docker",
                self.image, "sleep", "infinity",
            ],
            check=True,
            capture_output=True,
        )

    def _docker_exec(
        self, command: str, timeout: int = 120, stdin: bytes | None = None
    ) -> tuple[int, str, str]:
        argv = ["docker", "exec"]
        if stdin is not None:
            argv.append("-i")
        argv += [self.name, "bash", "-lc", command]
        proc = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            timeout=timeout,
        )
        decode = lambda b: (b or b"").decode("utf-8", errors="replace")  # noqa: E731
        return proc.returncode, decode(proc.stdout), decode(proc.stderr)

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        try:
            return self._docker_exec(command, timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s"

    def _abs(self, path: str) -> str:
        return path if path.startswith("/") else f"{self.workdir}/{path}"

    def write_file(self, path: str, content: str) -> str:
        """Stream the content over stdin.

        The previous implementation interpolated ``shlex.quote(content)`` into
        the command line, so any file bigger than ``ARG_MAX`` (~2 MB, and far
        less once quoting expands it) failed — which is to say, exactly the
        large observations the spill path writes.
        """
        target = self._abs(path)
        quoted = shlex.quote(target)
        code, _, err = self._docker_exec(
            f"mkdir -p $(dirname {quoted}) && cat > {quoted}",
            stdin=content.encode("utf-8"),
        )
        if code != 0:
            raise OSError(f"write failed: {err.strip()}")
        return target

    def read_file(self, path: str) -> str:
        code, out, err = self._docker_exec(f"cat {shlex.quote(self._abs(path))}")
        if code != 0:
            raise FileNotFoundError(err.strip())
        return out

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", self.volume], capture_output=True)
