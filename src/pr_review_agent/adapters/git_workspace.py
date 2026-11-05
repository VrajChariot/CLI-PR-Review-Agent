import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import ChangedFile, PullRequest
from ..errors import ConfigError, WorkspaceError

_STATUS = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type_changed",
}


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


@dataclass(frozen=True, slots=True)
class GitReviewWorkspace:
    root: Path
    base_sha: str
    head_sha: str

    def diff(self, path: str | None = None) -> str:
        args = ["diff", "--no-color", "--find-renames", f"{self.base_sha}...{self.head_sha}"]
        if path is not None:
            args += ["--", path]
        return _git(*args, cwd=self.root)

    def changed_files(self) -> list[ChangedFile]:
        out = _git(
            "diff", "--name-status", "--find-renames", f"{self.base_sha}...{self.head_sha}",
            cwd=self.root,
        )
        files: list[ChangedFile] = []
        for line in out.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            status = _STATUS.get(parts[0][0], "modified")
            if parts[0][0] in ("R", "C") and len(parts) >= 3:
                files.append(ChangedFile(path=parts[2], status=status, old_path=parts[1]))
            else:
                files.append(ChangedFile(path=parts[1], status=status, old_path=None))
        return files


class GitRepository:
    def __init__(self, repo_path: Path, remote: str) -> None:
        self._remote = remote
        try:
            top = _git("rev-parse", "--show-toplevel", cwd=repo_path).strip()
        except (WorkspaceError, OSError) as exc:
            raise ConfigError(f"not a git repository: {repo_path}") from exc
        self._repo = Path(top)

    def remote_url(self) -> str:
        try:
            return _git("remote", "get-url", self._remote, cwd=self._repo).strip()
        except WorkspaceError as exc:
            raise ConfigError(f"git remote '{self._remote}' not found in {self._repo}") from exc

    @contextmanager
    def checkout(self, pr: PullRequest) -> Iterator[GitReviewWorkspace]:
        _git(
            "fetch", "--no-tags", self._remote, pr.head_fetch_ref, pr.base_fetch_ref,
            cwd=self._repo,
        )
        for sha, ref in ((pr.head_sha, pr.head_fetch_ref), (pr.base_sha, pr.base_fetch_ref)):
            try:
                _git("cat-file", "-e", f"{sha}^{{commit}}", cwd=self._repo)
            except WorkspaceError as exc:
                raise WorkspaceError(
                    f"commit {sha} is not available after fetching {ref}; "
                    "the branch may have moved or been deleted — rerun the review"
                ) from exc
        tmp = Path(tempfile.mkdtemp(prefix="pr-review-"))
        worktree = tmp / "worktree"
        try:
            _git("worktree", "add", "--detach", str(worktree), pr.head_sha, cwd=self._repo)
            yield GitReviewWorkspace(root=worktree, base_sha=pr.base_sha, head_sha=pr.head_sha)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=self._repo, capture_output=True,
            )
            shutil.rmtree(tmp, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=self._repo, capture_output=True)
