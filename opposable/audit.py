"""The audit log: every command, URL and file, kept for 30 days.

Required by HOSTED_PRD §8/§11, but the reason to build it before launch is
narrower than compliance: when an abuse report arrives, the only useful
question is "what did that account actually run", and the answer has to
already exist. Reconstructing it from task workdirs after the fact does not
work, because the workdirs are exactly what an abuser deletes.

Append-only JSON lines, scrubbed on write. One file, because Stage 2 moves
this to Postgres alongside everything else and a second storage design now
would be thrown away.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

#: HOSTED_PRD §11: commands/URLs/spend 30-90 days. The floor is 30.
RETENTION_SECONDS = 30 * 24 * 3600

#: Long enough to identify what ran, short enough that the log is not a
#: second copy of everything the agent produced.
MAX_DETAIL_CHARS = 2_000


class AuditLog:
    def __init__(self, path: str | Path, retention: float = RETENTION_SECONDS):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention = retention
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        org_id: str = "",
        user_id: str = "",
        task_id: str = "",
        **detail,
    ) -> None:
        from .secrets_store import scrub

        entry = {
            "at": time.time(),
            "action": action,
            "org_id": org_id,
            "user_id": user_id,
            "task_id": task_id,
            "detail": {
                k: scrub(str(v))[:MAX_DETAIL_CHARS] if isinstance(v, str) else v
                for k, v in detail.items()
            },
        }
        line = scrub(json.dumps(entry, sort_keys=True, ensure_ascii=False))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def entries(self, action: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        out = [json.loads(line) for line in lines if line.strip()]
        return [e for e in out if action is None or e["action"] == action]

    def prune(self) -> int:
        """Drop entries past the retention window.

        Retention that is documented but not enforced is the gap regulators
        look for, so this is a real operation and not a comment in a policy.
        """
        if not self.path.exists():
            return 0
        cutoff = time.time() - self.retention
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            kept = [
                line for line in lines
                if line.strip() and json.loads(line).get("at", 0) >= cutoff
            ]
            removed = len([line for line in lines if line.strip()]) - len(kept)
            self.path.write_text(
                "".join(line + "\n" for line in kept), encoding="utf-8"
            )
        return removed
