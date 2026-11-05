import json

import httpx
import pytest

from pr_review_agent.adapters.azure_devops import AzureCoords, AzureDevOpsAdapter
from pr_review_agent.domain.models import InlineComment, PrState
from pr_review_agent.errors import PlatformError

COORDS = AzureCoords("https://dev.azure.com/org", "org", "My Project", "repo")


def adapter(handler) -> AzureDevOpsAdapter:
    return AzureDevOpsAdapter(COORDS, 9, "pat", httpx.Client(transport=httpx.MockTransport(handler)))


def pr_json(status="active", **over):
    d = {
        "status": status, "title": "t", "description": None, "isDraft": False,
        "createdBy": {"displayName": "Bob"},
        "sourceRefName": "refs/heads/feat", "targetRefName": "refs/heads/main",
        "lastMergeSourceCommit": {"commitId": "h" * 40},
        "lastMergeTargetCommit": {"commitId": "b" * 40},
    }
    d.update(over)
    return d


@pytest.mark.parametrize(
    "status,state",
    [("active", PrState.OPEN), ("completed", PrState.MERGED), ("abandoned", PrState.CLOSED)],
)
def test_status_mapping(status, state):
    pr = adapter(lambda r: httpx.Response(200, json=pr_json(status))).get_pull_request()
    assert pr.state == state
    assert (pr.source_branch, pr.head_fetch_ref) == ("feat", "refs/heads/feat")
    assert pr.web_url == "https://dev.azure.com/org/My%20Project/_git/repo/pullrequest/9"


def test_requests_carry_api_version_and_basic_auth():
    seen = {}

    def handler(request):
        seen["v"] = request.url.params["api-version"]
        seen["url"] = request.url.raw_path.decode().split("?")[0]
        return httpx.Response(200, json=pr_json())

    a = AzureDevOpsAdapter(COORDS, 9, "pat", None)
    a._client = httpx.Client(transport=httpx.MockTransport(handler), headers=a._client.headers)
    a.get_pull_request()
    assert seen["v"] == "7.1"
    assert seen["url"] == "/org/My%20Project/_apis/git/repositories/repo/pullRequests/9"
    assert a._client.headers["Authorization"].startswith("Basic ")


def test_comments_exclude_system_and_deleted():
    threads = {
        "value": [
            {"isDeleted": True, "comments": [{"content": "gone", "author": {"id": "1"}}]},
            {
                "threadContext": {"filePath": "/src/a.py", "rightFileStart": {"line": 4, "offset": 1}},
                "comments": [
                    {"content": "sys", "commentType": "system", "author": {"id": "0"}},
                    {"content": "del", "isDeleted": True, "author": {"id": "1"}},
                    {"content": "real", "commentType": "text", "author": {"id": "2", "displayName": "Al"}},
                ],
            },
        ]
    }
    comments = adapter(lambda r: httpx.Response(200, json=threads)).list_comments()
    assert len(comments) == 1
    c = comments[0]
    assert (c.author_id, c.author_name, c.body, c.path, c.line) == ("2", "Al", "real", "src/a.py", 4)


def test_inline_thread_payload():
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 33})

    a = adapter(handler)
    pr = adapter(lambda r: httpx.Response(200, json=pr_json())).get_pull_request()
    url = a.post_inline_comment(pr, InlineComment("src/a.py", 8, 6, "hi"))
    ctx = sent["body"]["threadContext"]
    assert ctx["filePath"] == "/src/a.py"
    assert (ctx["rightFileStart"]["line"], ctx["rightFileEnd"]["line"]) == (6, 8)
    assert sent["body"]["comments"][0]["content"] == "hi"
    assert url.endswith("/pullrequest/9?discussionId=33")


def test_203_is_auth_error():
    a = adapter(lambda r: httpx.Response(203, text="<html>sign in</html>"))
    with pytest.raises(PlatformError, match="AZURE_DEVOPS_PAT"):
        a.get_pull_request()


def test_file_link_format():
    pr = adapter(lambda r: httpx.Response(200, json=pr_json())).get_pull_request()
    link = adapter(lambda r: None).file_link(pr, "src/a b.py", 4, 7)
    assert link == (
        "https://dev.azure.com/org/My%20Project/_git/repo?path=/src/a%20b.py"
        f"&version=GC{'h' * 40}&line=4&lineEnd=8&lineStartColumn=1&lineEndColumn=1"
        "&lineStyle=plain&_a=contents"
    )
