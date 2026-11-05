import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from ..domain.models import Platform
from ..errors import ConfigError


def default_state_path(platform: Platform, remote_url: str, env: Mapping[str, str]) -> Path:
    base = Path(env.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    digest = hashlib.sha1(remote_url.encode()).hexdigest()[:12]
    return base / "pr-review" / f"{platform.value}-{digest}.json"


class JsonWatchState:
    """Last reviewed head SHA per PR number, persisted as JSON for one remote."""

    def __init__(self, path: Path, remote_url: str) -> None:
        self._path = path
        self._remote_url = remote_url
        self._reviewed: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        corrupt = ConfigError(
            f"watch state file {self._path} is corrupt or belongs to another remote; "
            "delete it to start over"
        )
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise corrupt from exc
        if not isinstance(data, dict) or data.get("remote") != self._remote_url:
            raise corrupt
        reviewed = data.get("reviewed")
        if not isinstance(reviewed, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in reviewed.items()
        ):
            raise corrupt
        return reviewed

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"remote": self._remote_url, "reviewed": self._reviewed}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def last_reviewed(self, number: int) -> str | None:
        return self._reviewed.get(str(number))

    def record(self, number: int, head_sha: str) -> None:
        self._reviewed[str(number)] = head_sha
        self._save()

    def retain(self, open_numbers: set[int]) -> None:
        keep = {str(n) for n in open_numbers}
        pruned = {k: v for k, v in self._reviewed.items() if k in keep}
        if pruned != self._reviewed:
            self._reviewed = pruned
            self._save()
