import subprocess
from pathlib import Path

import pytest

from pr_review_agent.adapters.git_workspace import GitRepository
from pr_review_agent.domain.models import PrState, PullRequest
from pr_review_agent.errors import ConfigError, WorkspaceError


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("clone", str(origin), str(seed), cwd=tmp_path)
    git("checkout", "-b", "main", cwd=seed)
    (seed / "README.md").write_text("hi\n")
    git("add", ".", cwd=seed)
    git("commit", "-m", "init", cwd=seed)
    git("push", "origin", "main", cwd=seed)
    git("checkout", "-b", "feature", cwd=seed)
    (seed / "lib.py").write_text('print("x")\n')
    (seed / "README.md").write_text("hi there\n")
    git("add", ".", cwd=seed)
    git("commit", "-m", "feature", cwd=seed)
    git("push", "origin", "feature", cwd=seed)
    work = tmp_path / "work"
    git("clone", str(origin), str(work), cwd=tmp_path)
    return work, git("rev-parse", "origin/main", cwd=work), git("rev-parse", "origin/feature", cwd=work)


def make_pr(base, head):
    return PullRequest(
        1, "t", "", "a", PrState.OPEN, False, "feature", "main", head, base, "u",
        "refs/heads/feature", "refs/heads/main",
    )


def worktrees(repo):
    return [l for l in git("worktree", "list", "--porcelain", cwd=repo).splitlines() if l.startswith("worktree ")]


def test_checkout_diff_and_changed_files(clone):
    work, base, head = clone
    repo = GitRepository(work, "origin")
    assert repo.remote_url().endswith("origin.git")
    with repo.checkout(make_pr(base, head)) as ws:
        assert git("rev-parse", "HEAD", cwd=ws.root) == head
        assert 'print("x")' in ws.diff()
        assert "+hi there" not in ws.diff("lib.py")
        files = {f.path: f.status for f in ws.changed_files()}
        assert files == {"lib.py": "added", "README.md": "modified"}
        root = ws.root
    assert not root.exists() and not root.parent.exists()
    assert len(worktrees(work)) == 1


def test_cleanup_when_body_raises(clone):
    work, base, head = clone
    repo = GitRepository(work, "origin")
    with pytest.raises(RuntimeError):
        with repo.checkout(make_pr(base, head)) as ws:
            root = ws.root
            raise RuntimeError("boom")
    assert not root.parent.exists()
    assert len(worktrees(work)) == 1


def test_unknown_head_sha(clone):
    work, base, _ = clone
    with pytest.raises(WorkspaceError, match="is not available after fetching"):
        with GitRepository(work, "origin").checkout(make_pr(base, "0" * 40)):
            pass


def test_config_errors(tmp_path, clone):
    with pytest.raises(ConfigError, match="not a git repository"):
        GitRepository(tmp_path / "nope", "origin")
    with pytest.raises(ConfigError, match="remote 'upstream' not found"):
        GitRepository(clone[0], "upstream").remote_url()
