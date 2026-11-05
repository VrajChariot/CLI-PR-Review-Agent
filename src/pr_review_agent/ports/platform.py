from typing import Protocol

from ..domain.models import Account, InlineComment, Platform, PrComment, PullRequest


class PullRequestPort(Protocol):
    platform: Platform

    def get_pull_request(self) -> PullRequest: ...

    def get_authenticated_account(self) -> Account: ...

    def list_comments(self) -> list[PrComment]: ...

    def post_summary_comment(self, body: str) -> str:
        """Post a PR-level comment; returns its URL."""
        ...

    def post_inline_comment(self, pr: PullRequest, comment: InlineComment) -> str:
        """Post a comment anchored to a line of the PR head; returns its URL."""
        ...

    def file_link(self, pr: PullRequest, path: str, start_line: int, end_line: int) -> str: ...
