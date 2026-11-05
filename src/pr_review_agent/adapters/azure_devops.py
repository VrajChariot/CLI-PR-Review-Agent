import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

import httpx

from ..domain.models import (
    Account,
    InlineComment,
    Platform,
    PrComment,
    PrState,
    PullRequest,
)
from ..errors import ConfigError, PlatformError

API_VERSION = "7.1"

_PR_SUFFIX = r"(?:/pullrequest/(?P<pr>\d+)(?:[/?#].*)?)?"
_HTTPS_PATTERNS = (
    re.compile(
        r"^https://(?:[^@/]+@)?dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/"
        r"(?P<repo>[^/?#]+?)" + _PR_SUFFIX + r"/?$"
    ),
    re.compile(
        r"^https://(?P<org>[^/.@]+)\.visualstudio\.com/(?:DefaultCollection/)?"
        r"(?P<project>[^/]+)/_git/(?P<repo>[^/?#]+?)" + _PR_SUFFIX + r"/?$"
    ),
)
_SSH_PATTERN = re.compile(
    r"^(?:ssh://)?git@ssh\.dev\.azure\.com[:/]v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/]+?)/?$"
)


@dataclass(frozen=True, slots=True)
class AzureCoords:
    base_url: str
    organization: str
    project: str
    repository: str

    def key(self) -> tuple[str, str, str]:
        return (self.organization.lower(), self.project.lower(), self.repository.lower())

    def display(self) -> str:
        return f"{self.organization}/{self.project}/{self.repository}"


def _coords(m: re.Match[str], base_url: str) -> AzureCoords:
    return AzureCoords(
        base_url=base_url,
        organization=unquote(m["org"]),
        project=unquote(m["project"]),
        repository=unquote(m["repo"]),
    )


def _match_https(url: str) -> tuple[AzureCoords, int | None] | None:
    url = url.strip()
    for i, pattern in enumerate(_HTTPS_PATTERNS):
        m = pattern.match(url)
        if m:
            base = (
                f"https://dev.azure.com/{m['org']}"
                if i == 0
                else f"https://{m['org']}.visualstudio.com"
            )
            return _coords(m, base), int(m["pr"]) if m["pr"] else None
    return None


def parse_azure_remote(url: str) -> AzureCoords | None:
    url = url.strip()
    m = _SSH_PATTERN.match(url)
    if m:
        return _coords(m, f"https://dev.azure.com/{m['org']}")
    matched = _match_https(url)
    if matched and matched[1] is None:
        return matched[0]
    return None


def parse_azure_pr_url(url: str) -> tuple[AzureCoords, int] | None:
    matched = _match_https(url)
    if matched and matched[1] is not None:
        return matched[0], matched[1]
    return None


def azure_repository_from_remote(
    remote_url: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> "AzureRepository":
    coords = parse_azure_remote(remote_url)
    if coords is None:
        raise ConfigError(
            f"--adapter azure, but remote URL {remote_url} is not an Azure DevOps repository"
        )
    pat = env.get("AZURE_DEVOPS_PAT")
    if not pat:
        raise ConfigError("AZURE_DEVOPS_PAT is required for --adapter azure")
    return AzureRepository(coords, pat, client)


def azure_from_args(
    remote_url: str,
    pr_arg: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> "AzureDevOpsAdapter":
    repository = azure_repository_from_remote(remote_url, env, client)
    coords = repository.coords
    if pr_arg.isdigit():
        number = int(pr_arg)
    else:
        parsed = parse_azure_pr_url(pr_arg)
        if parsed is None:
            raise ConfigError(
                f"--pr must be a PR number or an Azure DevOps pull request URL, got {pr_arg!r}"
            )
        url_coords, number = parsed
        if url_coords.key() != coords.key():
            raise ConfigError(
                f"PR URL is for {url_coords.display()} but remote points to {coords.display()}"
            )
    return repository.pull_request(number)


def _strip_heads(ref: str) -> str:
    return ref.removeprefix("refs/heads/")


def _web_url(coords: AzureCoords, number: int) -> str:
    return (
        f"{coords.base_url}/{quote(coords.project)}/_git/{quote(coords.repository)}"
        f"/pullrequest/{number}"
    )


def _to_pull_request(d: dict[str, Any], number: int, web_url: str) -> PullRequest:
    state = {
        "active": PrState.OPEN,
        "completed": PrState.MERGED,
        "abandoned": PrState.CLOSED,
    }[d["status"]]
    return PullRequest(
        number=number,
        title=d["title"],
        description=d.get("description") or "",
        author=d["createdBy"]["displayName"],
        state=state,
        is_draft=bool(d.get("isDraft")),
        source_branch=_strip_heads(d["sourceRefName"]),
        target_branch=_strip_heads(d["targetRefName"]),
        head_sha=d["lastMergeSourceCommit"]["commitId"],
        base_sha=d["lastMergeTargetCommit"]["commitId"],
        web_url=web_url,
        head_fetch_ref=d["sourceRefName"],
        base_fetch_ref=d["targetRefName"],
    )


_PAGE_SIZE = 100


class AzureRepository:
    """Repository-level Azure DevOps client: lists active PRs and hands out per-PR adapters."""

    platform = Platform.AZURE

    def __init__(
        self,
        coords: AzureCoords,
        pat: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.coords = coords
        self._client = client or httpx.Client(
            timeout=30,
            headers={
                "Authorization": "Basic " + base64.b64encode(f":{pat}".encode()).decode(),
                "Accept": "application/json",
                "User-Agent": "pr-review-agent",
            },
        )

    def _request(
        self, method: str, url: str, *, versioned: bool = True, **kwargs: Any
    ) -> httpx.Response:
        if versioned:
            kwargs["params"] = {**kwargs.get("params", {}), "api-version": API_VERSION}
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise PlatformError(f"Azure DevOps API {method} {url} failed: {exc}") from exc
        if response.status_code in (203, 401):
            raise PlatformError(
                "Azure DevOps authentication failed; check AZURE_DEVOPS_PAT "
                "(needs Code: Read & Write)"
            )
        if not response.is_success:
            try:
                detail = response.json().get("message", response.text)
            except ValueError:
                detail = response.text
            raise PlatformError(
                f"Azure DevOps API {method} {url} failed: {response.status_code} {detail}"
            )
        return response

    def list_open_pull_requests(self) -> list[PullRequest]:
        c = self.coords
        url = (
            f"{c.base_url}/{quote(c.project)}/_apis/git/repositories/"
            f"{quote(c.repository)}/pullrequests"
        )
        items: list[dict[str, Any]] = []
        while True:
            params = {
                "searchCriteria.status": "active",
                "$top": _PAGE_SIZE,
                "$skip": len(items),
            }
            page = self._request("GET", url, params=params).json().get("value", [])
            items.extend(page)
            if len(page) < _PAGE_SIZE:
                break
        prs: list[PullRequest] = []
        for d in items:
            number = d["pullRequestId"]
            if "lastMergeSourceCommit" in d and "lastMergeTargetCommit" in d:
                prs.append(_to_pull_request(d, number, _web_url(c, number)))
            else:
                # Listing omits merge commits until a merge was computed; the detail call waits for it.
                prs.append(AzureDevOpsAdapter(self, number).get_pull_request())
        return sorted(prs, key=lambda pr: pr.number)

    def pull_request(self, number: int) -> "AzureDevOpsAdapter":
        return AzureDevOpsAdapter(self, number)


class AzureDevOpsAdapter:
    platform = Platform.AZURE

    def __init__(self, repository: AzureRepository, number: int) -> None:
        self._repository = repository
        self._coords = repository.coords
        self._number = number

    @property
    def _project(self) -> str:
        return quote(self._coords.project)

    @property
    def _prefix(self) -> str:
        c = self._coords
        return (
            f"{c.base_url}/{self._project}/_apis/git/repositories/"
            f"{quote(c.repository)}/pullRequests/{self._number}"
        )

    @property
    def _web_url(self) -> str:
        return _web_url(self._coords, self._number)

    def _request(
        self, method: str, url: str, *, versioned: bool = True, **kwargs: Any
    ) -> httpx.Response:
        return self._repository._request(method, url, versioned=versioned, **kwargs)

    def get_pull_request(self) -> PullRequest:
        d = self._request("GET", self._prefix).json()
        return _to_pull_request(d, self._number, self._web_url)

    def get_authenticated_account(self) -> Account:
        url = f"{self._coords.base_url}/_apis/connectionData"
        user = self._request("GET", url, versioned=False).json()["authenticatedUser"]
        return Account(id=user["id"], name=user.get("providerDisplayName", ""))

    def list_comments(self) -> list[PrComment]:
        threads = self._request("GET", f"{self._prefix}/threads").json().get("value", [])
        comments: list[PrComment] = []
        for thread in threads:
            if thread.get("isDeleted"):
                continue
            ctx = thread.get("threadContext") or {}
            file_path = ctx.get("filePath")
            path = file_path.lstrip("/") if file_path else None
            line = (ctx.get("rightFileStart") or {}).get("line")
            for c in thread.get("comments", []):
                if c.get("isDeleted") or c.get("commentType") == "system":
                    continue
                author = c.get("author") or {}
                comments.append(
                    PrComment(
                        author_id=author.get("id", ""),
                        author_name=author.get("displayName", ""),
                        body=c.get("content") or "",
                        path=path,
                        line=line,
                    )
                )
        return comments

    def _post_thread(self, body: str, thread_context: dict[str, Any] | None) -> str:
        payload: dict[str, Any] = {
            "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
            "status": 1,
        }
        if thread_context is not None:
            payload["threadContext"] = thread_context
        thread = self._request("POST", f"{self._prefix}/threads", json=payload).json()
        return f"{self._web_url}?discussionId={thread['id']}"

    def post_summary_comment(self, body: str) -> str:
        return self._post_thread(body, None)

    def post_inline_comment(self, pr: PullRequest, comment: InlineComment) -> str:
        return self._post_thread(
            comment.body,
            {
                "filePath": "/" + comment.path,
                "rightFileStart": {"line": comment.start_line or comment.line, "offset": 1},
                "rightFileEnd": {"line": comment.line, "offset": 1},
            },
        )

    def file_link(self, pr: PullRequest, path: str, start_line: int, end_line: int) -> str:
        c = self._coords
        return (
            f"{c.base_url}/{self._project}/_git/{quote(c.repository)}"
            f"?path=/{quote(path, safe='/')}&version=GC{pr.head_sha}"
            f"&line={start_line}&lineEnd={end_line + 1}&lineStartColumn=1&lineEndColumn=1"
            f"&lineStyle=plain&_a=contents"
        )
