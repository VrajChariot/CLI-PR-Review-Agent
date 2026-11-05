import time
from collections.abc import Callable
from typing import TextIO

from ..errors import AgentError, PlatformError, WorkspaceError
from ..ports.agent import ReviewAgentPort
from ..ports.platform import PullRequestSourcePort
from ..ports.watch_state import WatchStatePort
from ..ports.workspace import RepositoryPort
from .review_service import ReviewService


class WatchService:
    """Polls open PRs and reviews each new head commit once, posting findings on the PR."""

    def __init__(
        self,
        source: PullRequestSourcePort,
        repository: RepositoryPort,
        agent: ReviewAgentPort,
        state: WatchStatePort,
        out: TextIO,
        err: TextIO,
        interval: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._source = source
        self._repository = repository
        self._agent = agent
        self._state = state
        self._out = out
        self._err = err
        self._interval = interval
        self._sleep = sleep

    def run_forever(self) -> None:
        while True:
            self.run_once()
            self._sleep(self._interval)

    def run_once(self) -> None:
        try:
            prs = self._source.list_open_pull_requests()
        except PlatformError as exc:
            print(f"poll failed: {exc}", file=self._err, flush=True)
            return
        # Closed or merged PRs leave the state, so a reopened PR is reviewed again.
        self._state.retain({pr.number for pr in prs})
        for pr in sorted(prs, key=lambda p: p.number):
            # Drafts are not recorded: they are reviewed once marked ready.
            if pr.is_draft or self._state.last_reviewed(pr.number) == pr.head_sha:
                continue
            print(f"→ PR #{pr.number} {pr.title} @ {pr.head_sha[:7]}", file=self._err, flush=True)
            service = ReviewService(
                self._source.pull_request(pr.number), self._repository, self._agent
            )
            try:
                outcome = service.run(post_comments=True, post_summary=False)
            except (PlatformError, WorkspaceError, AgentError) as exc:
                # Unrecorded, so the next poll retries it.
                print(f"✗ PR #{pr.number} failed: {exc}", file=self._err, flush=True)
                continue
            if outcome.reviewed_head_sha is None:
                continue  # closed or turned draft since listing
            self._state.record(pr.number, outcome.reviewed_head_sha)
            if outcome.posted_urls:
                line = f"✎ PR #{pr.number} posted {len(outcome.posted_urls)} comment(s)"
            else:
                line = f"✓ PR #{pr.number} no new issues"
            print(f"{line} · {pr.web_url}", file=self._out, flush=True)
