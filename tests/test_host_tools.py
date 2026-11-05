from pathlib import Path

import pytest

from pr_review_agent.adapters.omp_agent import build_host_tools
from pr_review_agent.domain.models import (
    REVIEW_MARKER,
    Account,
    ChangedFile,
    Platform,
    PrState,
    PullRequest,
    ensure_marker,
)
from pr_review_agent.ports.agent import ReviewJob


class FakePlatform:
    platform = Platform.GITHUB

    def __init__(self):
        self.summaries, self.inlines = [], []

    def get_authenticated_account(self):
        return Account("me", "Me")

    def list_comments(self):
        return []

    def post_summary_comment(self, body):
        self.summaries.append(body)
        return "url-summary"

    def post_inline_comment(self, pr, comment):
        self.inlines.append(comment)
        return "url-inline"

    def file_link(self, pr, path, s, e):
        return f"link:{path}:{s}-{e}"


class FakeWorkspace:
    root = Path("/tmp")

    def diff(self, path=None):
        return ""

    def changed_files(self):
        return [ChangedFile("a.py", "modified", None)]


PR = PullRequest(1, "t", "", "a", PrState.OPEN, False, "f", "main", "h", "b", "u", "rh", "rb")


def tools_for(post: bool):
    platform = FakePlatform()
    tools = {t.name: t for t in build_host_tools(ReviewJob(PR, platform, FakeWorkspace(), post))}
    return platform, tools


def call(tools, name, **args):
    return tools[name].execute(args, None)


def test_posting_tools_only_with_comment_flag():
    _, without = tools_for(False)
    _, with_ = tools_for(True)
    posting = {"pr_post_summary_comment", "pr_post_inline_comment"}
    assert not posting & without.keys()
    assert posting <= with_.keys()
    assert all(t.load_mode == "essential" for t in with_.values())


def test_marker_appended_once():
    platform, tools = tools_for(True)
    call(tools, "pr_post_summary_comment", body="hello")
    assert platform.summaries[0].count(REVIEW_MARKER) == 1
    assert ensure_marker(platform.summaries[0]) == platform.summaries[0]


def test_summary_posted_once_per_run():
    platform, tools = tools_for(True)
    call(tools, "pr_post_summary_comment", body="one")
    assert call(tools, "pr_post_summary_comment", body="two").startswith("Duplicate")
    assert len(platform.summaries) == 1


def test_identical_inline_posted_once_and_marker_present():
    platform, tools = tools_for(True)
    assert call(tools, "pr_post_inline_comment", path="a.py", line=3, body="x") == "url-inline"
    assert call(tools, "pr_post_inline_comment", path="a.py", line=3, body="x").startswith("Duplicate")
    call(tools, "pr_post_inline_comment", path="a.py", line=4, body="x")
    assert len(platform.inlines) == 2
    assert all(REVIEW_MARKER in c.body for c in platform.inlines)


def test_inline_on_unchanged_path_raises():
    platform, tools = tools_for(True)
    with pytest.raises(ValueError, match="z.py is not changed in this PR"):
        call(tools, "pr_post_inline_comment", path="z.py", line=1, body="x")
    assert platform.inlines == []


def test_file_link_validates_range():
    _, tools = tools_for(False)
    assert call(tools, "pr_file_link", path="a.py", start_line=2, end_line=5) == "link:a.py:2-5"
    with pytest.raises(ValueError, match="start_line must be <= end_line"):
        call(tools, "pr_file_link", path="a.py", start_line=6, end_line=5)


def test_empty_diff_messages():
    _, tools = tools_for(False)
    assert call(tools, "pr_diff") == "Empty diff."
    assert call(tools, "pr_diff", path="a.py") == "No changes for a.py."
