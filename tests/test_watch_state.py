import json
from pathlib import Path

import pytest

from pr_review_agent.adapters.watch_state import JsonWatchState, default_state_path
from pr_review_agent.domain.models import Platform
from pr_review_agent.errors import ConfigError

REMOTE = "https://github.com/acme/widgets.git"


def test_missing_file_is_empty_state(tmp_path: Path):
    state = JsonWatchState(tmp_path / "s" / "state.json", REMOTE)
    assert state.last_reviewed(1) is None


def test_record_persists_across_instances_and_creates_parents(tmp_path: Path):
    path = tmp_path / "deep" / "state.json"
    JsonWatchState(path, REMOTE).record(7, "abc")
    assert JsonWatchState(path, REMOTE).last_reviewed(7) == "abc"
    assert json.loads(path.read_text()) == {"remote": REMOTE, "reviewed": {"7": "abc"}}
    assert not path.with_suffix(".tmp").exists()


def test_retain_prunes_closed_prs_and_persists(tmp_path: Path):
    path = tmp_path / "state.json"
    state = JsonWatchState(path, REMOTE)
    state.record(1, "a")
    state.record(2, "b")
    state.retain({2, 3})
    assert state.last_reviewed(1) is None
    assert JsonWatchState(path, REMOTE).last_reviewed(2) == "b"
    assert JsonWatchState(path, REMOTE).last_reviewed(1) is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"remote": "other", "reviewed": {}}),
        json.dumps({"remote": REMOTE, "reviewed": {"1": 5}}),
        json.dumps({"remote": REMOTE}),
    ],
)
def test_corrupt_or_foreign_state_raises(tmp_path: Path, content: str):
    path = tmp_path / "state.json"
    path.write_text(content)
    with pytest.raises(ConfigError, match="corrupt or belongs to another remote"):
        JsonWatchState(path, REMOTE)


def test_default_state_path_honours_xdg_state_home(tmp_path: Path):
    p = default_state_path(Platform.GITHUB, REMOTE, {"XDG_STATE_HOME": str(tmp_path)})
    assert p.parent == tmp_path / "pr-review"
    assert p.name.startswith("github-") and p.suffix == ".json"
    other = default_state_path(Platform.GITHUB, REMOTE + "x", {"XDG_STATE_HOME": str(tmp_path)})
    assert other != p


def test_default_state_path_falls_back_to_home():
    p = default_state_path(Platform.AZURE, REMOTE, {})
    assert p.parts[-4:-1] == (".local", "state", "pr-review")
