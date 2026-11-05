import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

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

_REMOTE_PATTERNS = (
    re.compile(r"^https://(?:[^@/]+@)?github\.com/(?P<o>[^/]+)/(?P<r>[^/]+?)(?:\.git)?/?$"),
    re.compile(r"^git@github\.com:(?P<o>[^/]+)/(?P<r>[^/]+?)(?:\.git)?/?$"),
    re.compile(r"^ssh://git@github\.com/(?P<o>[^/]+)/(?P<r>[^/]+?)(?:\.git)?/?$"),
)
_PR_URL = re.compile(
    r"^https://github\.com/(?P<o>[^/]+)/(?P<r>[^/]+)/pull/(?P<n>\d+)(?:[/?#].*)?$"
)


def parse_github_remote(url: str) -> tuple[str, str] | None:
    url = url.strip()
    for pattern in _REMOTE_PATTERNS:
        m = pattern.match(url)
        if m:
            return m["o"], m["r"]
    return None


def parse_github_pr_url(url: str) -> tuple[str, str, int] | None:
    m = _PR_URL.match(url.strip())
    return (m["o"], m["r"], int(m["n"])) if m else None


def github_repository_from_remote(
    remote_url: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> "GitHubRepository":
    remote = parse_github_remote(remote_url)
    if remote is None:
        raise ConfigError(
            f"--adapter github, but remote URL {remote_url} is not a github.com repository"
        )
    owner, repo = remote
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not token:
        raise ConfigError("GITHUB_TOKEN (or GH_TOKEN) is required for --adapter github")
    return GitHubRepository(owner, repo, token, client)


def github_from_args(
    remote_url: str,
    pr_arg: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> "GitHubAdapter":
    repository = github_repository_from_remote(remote_url, env, client)
    owner, repo = repository.owner, repository.repo
    if pr_arg.isdigit():
        number = int(pr_arg)
    else:
        parsed = parse_github_pr_url(pr_arg)
        if parsed is None:
            raise ConfigError(
                f"--pr must be a PR number or a GitHub pull request URL, got {pr_arg!r}"
            )
        o, r, number = parsed
        if (o.lower(), r.lower()) != (owner.lower(), repo.lower()):
            raise ConfigError(f"PR URL is for {o}/{r} but remote points to {owner}/{repo}")
    return repository.pull_request(number)


def _to_pull_request(d: dict[str, Any], number: int) -> PullRequest:
    if d.get("merged_at"):
        state = PrState.MERGED
    elif d["state"] == "closed":
        state = PrState.CLOSED
    else:
        state = PrState.OPEN
    return PullRequest(
        number=number,
        title=d["title"],
        description=d.get("body") or "",
        author=d["user"]["login"],
        state=state,
        is_draft=bool(d.get("draft")),
        source_branch=d["head"]["ref"],
        target_branch=d["base"]["ref"],
        head_sha=d["head"]["sha"],
        base_sha=d["base"]["sha"],
        web_url=d["html_url"],
        head_fetch_ref=f"refs/pull/{number}/head",
        base_fetch_ref=f"refs/heads/{d['base']['ref']}",
    )


class GitHubRepository:
    """Repository-level GitHub client: lists open PRs and hands out per-PR adapters."""

    platform = Platform.GITHUB

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self._client = client or httpx.Client(
            base_url="https://api.github.com",
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pr-review-agent",
            },
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise PlatformError(f"GitHub API {method} {path} failed: {exc}") from exc
        if not response.is_success:
            try:
                detail = response.json().get("message", response.text)
            except ValueError:
                detail = response.text
            raise PlatformError(
                f"GitHub API {method} {path} failed: {response.status_code} {detail}"
            )
        return response

    def _paginate(self, path: str, **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        response = self._request("GET", path, params={"per_page": 100, **params})
        while True:
            items.extend(response.json())
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items
            response = self._request("GET", next_url)

    def list_open_pull_requests(self) -> list[PullRequest]:
        items = self._paginate(f"/repos/{self.owner}/{self.repo}/pulls", state="open")
        return sorted(
            (_to_pull_request(d, d["number"]) for d in items), key=lambda pr: pr.number
        )

    def pull_request(self, number: int) -> "GitHubAdapter":
        return GitHubAdapter(self, number)


class GitHubAdapter:
    platform = Platform.GITHUB

    def __init__(self, repository: GitHubRepository, number: int) -> None:
        self._repository = repository
        self._number = number

    @property
    def _owner(self) -> str:
        return self._repository.owner

    @property
    def _repo(self) -> str:
        return self._repository.repo

    @property
    def _repo_path(self) -> str:
        return f"/repos/{self._owner}/{self._repo}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._repository._request(method, path, **kwargs)

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        return self._repository._paginate(path)

    def get_pull_request(self) -> PullRequest:
        d = self._request("GET", f"{self._repo_path}/pulls/{self._number}").json()
        return _to_pull_request(d, self._number)

    def get_authenticated_account(self) -> Account:
        login = self._request("GET", "/user").json()["login"]
        return Account(id=login, name=login)

    def list_comments(self) -> list[PrComment]:
        base = f"{self._repo_path}"
        n = self._number
        comments: list[PrComment] = []
        for c in self._paginate(f"{base}/issues/{n}/comments"):
            login = c["user"]["login"]
            comments.append(PrComment(login, login, c.get("body") or "", None, None))
        for c in self._paginate(f"{base}/pulls/{n}/comments"):
            login = c["user"]["login"]
            line = c.get("line") or c.get("original_line")
            comments.append(PrComment(login, login, c.get("body") or "", c.get("path"), line))
        for c in self._paginate(f"{base}/pulls/{n}/reviews"):
            if c.get("body"):
                login = c["user"]["login"]
                comments.append(PrComment(login, login, c["body"], None, None))
        return comments

    def post_summary_comment(self, body: str) -> str:
        r = self._request(
            "POST", f"{self._repo_path}/issues/{self._number}/comments", json={"body": body}
        )
        return r.json()["html_url"]

    def post_inline_comment(self, pr: PullRequest, comment: InlineComment) -> str:
        payload: dict[str, Any] = {
            "body": comment.body,
            "commit_id": pr.head_sha,
            "path": comment.path,
            "line": comment.line,
            "side": "RIGHT",
        }
        if comment.start_line is not None and comment.start_line < comment.line:
            payload["start_line"] = comment.start_line
            payload["start_side"] = "RIGHT"
        r = self._request(
            "POST", f"{self._repo_path}/pulls/{self._number}/comments", json=payload
        )
        return r.json()["html_url"]

    def file_link(self, pr: PullRequest, path: str, start_line: int, end_line: int) -> str:
        return (
            f"https://github.com/{self._owner}/{self._repo}/blob/{pr.head_sha}/"
            f"{quote(path, safe='/')}#L{start_line}-L{end_line}"
        )
