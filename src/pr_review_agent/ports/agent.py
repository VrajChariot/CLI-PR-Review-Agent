from dataclasses import dataclass
from typing import Protocol

from ..domain.models import PullRequest
from .platform import PullRequestPort
from .workspace import ReviewWorkspace


@dataclass(frozen=True, slots=True)
class ReviewJob:
    pr: PullRequest
    platform: PullRequestPort
    workspace: ReviewWorkspace
    post_comments: bool


class ReviewAgentPort(Protocol):
    def review(self, job: ReviewJob) -> str:
        """Run the review; returns the terminal report text."""
        ...
