import json

import httpx
import pytest

from pr_review_agent.adapters.github import GitHubAdapter
from pr_review_agent.domain.models import InlineComment, PrState
from pr_review_agent.errors import PlatformError


def adapter(handler) -> GitHubAdapter:
    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    return GitHubAdapter("acme", "widgets", 7, "tok", client)


def pr_json(**over):
    d = {
        "title": "t", "body": None, "user": {"login": "bob"}, "state": "open",
        "merged_at": None, "draft": False, "html_url": "https://github.com/acme/widgets/pull/7",
        "head": {"ref": "feat", "sha": "h" * 40}, "base": {"ref": "main", "sha": "b" * 40},
    }
    d.update(over)
    return d


@pytest.mark.parametrize(
    "over,state,draft",
    [
        ({"state": "closed", "merged_at": "2024-01-01T00:00:00Z"}, PrState.MERGED, False),
        ({"state": "closed"}, PrState.CLOSED, False),
        ({"draft": True}, PrState.OPEN, True),
    ],
)
def test_state_mapping(over, state, draft):
    pr = adapter(lambda r: httpx.Response(200, json=pr_json(**over))).get_pull_request()
    assert (pr.state, pr.is_draft) == (state, draft)
    assert pr.head_fetch_ref == "refs/pull/7/head"
    assert pr.base_fetch_ref == "refs/heads/main"
    assert pr.description == ""


def test_comment_pagination_follows_link_header():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        path = request.url.path
        if path.endswith("/issues/7/comments"):
            if request.url.params.get("page") == "2":
                return httpx.Response(200, json=[{"user": {"login": "b"}, "body": "two"}])
            return httpx.Response(
                200,
                json=[{"user": {"login": "a"}, "body": "one"}],
                headers={
                    "Link": '<https://api.github.com/repos/acme/widgets/issues/7/comments?page=2>; rel="next"'
                },
            )
        if path.endswith("/pulls/7/comments"):
            return httpx.Response(
                200,
                json=[{"user": {"login": "c"}, "body": "inline", "path": "x.py", "line": None, "original_line": 9}],
            )
        if path.endswith("/pulls/7/reviews"):
            return httpx.Response(
                200,
                json=[
                    {"user": {"login": "d"}, "body": ""},
                    {"user": {"login": "e"}, "body": "review body"},
                ],
            )
        raise AssertionError(path)

    comments = adapter(handler).list_comments()
    assert [c.body for c in comments] == ["one", "two", "inline", "review body"]
    assert (comments[2].path, comments[2].line) == ("x.py", 9)


def test_inline_payload_anchors_to_head_and_start_line_only_when_smaller():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(201, json={"html_url": "https://u"})

    a = adapter(handler)
    pr = adapter(lambda r: httpx.Response(200, json=pr_json())).get_pull_request()
    a.post_inline_comment(pr, InlineComment("a.py", 5, None, "b"))
    a.post_inline_comment(pr, InlineComment("a.py", 5, 5, "b"))
    a.post_inline_comment(pr, InlineComment("a.py", 5, 3, "b"))
    for p in sent:
        assert (p["commit_id"], p["side"]) == ("h" * 40, "RIGHT")
    assert "start_line" not in sent[0] and "start_line" not in sent[1]
    assert (sent[2]["start_line"], sent[2]["start_side"]) == (3, "RIGHT")


def test_api_error_includes_message():
    a = adapter(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(PlatformError, match="404 Not Found"):
        a.get_pull_request()
