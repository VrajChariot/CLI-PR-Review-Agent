from dataclasses import dataclass
from enum import StrEnum

REVIEW_MARKER = "<!-- agent-code-review -->"


class Platform(StrEnum):
    GITHUB = "github"
    AZURE = "azure"

    @property
    def display_name(self) -> str:
        return "GitHub" if self is Platform.GITHUB else "Azure DevOps"


class PrState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    title: str
    description: str
    author: str
    state: PrState
    is_draft: bool
    source_branch: str
    target_branch: str
    head_sha: str
    base_sha: str
    web_url: str
    head_fetch_ref: str
    base_fetch_ref: str


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class PrComment:
    author_id: str
    author_name: str
    body: str
    path: str | None
    line: int | None


@dataclass(frozen=True, slots=True)
class InlineComment:
    path: str
    line: int
    start_line: int | None
    body: str


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    status: str  # added|modified|deleted|renamed|copied|type_changed
    old_path: str | None


def ensure_marker(body: str) -> str:
    if REVIEW_MARKER in body:
        return body
    return body.rstrip() + "\n\n" + REVIEW_MARKER


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    report: str
    posted_urls: tuple[str, ...]
    reviewed_head_sha: str | None  # None = skipped by the eligibility gate
