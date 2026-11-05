from ..domain.models import PrState, ReviewOutcome
from ..ports.agent import ReviewAgentPort, ReviewJob
from ..ports.platform import PullRequestPort
from ..ports.workspace import RepositoryPort


class ReviewService:
    def __init__(
        self,
        platform: PullRequestPort,
        repository: RepositoryPort,
        agent: ReviewAgentPort,
    ) -> None:
        self._platform = platform
        self._repository = repository
        self._agent = agent

    def run(self, post_comments: bool, post_summary: bool = True) -> ReviewOutcome:
        pr = self._platform.get_pull_request()
        # Deterministic gate: a merged/abandoned PR's branch may no longer be fetchable.
        if pr.state != PrState.OPEN:
            return ReviewOutcome(f"Skipped: PR #{pr.number} is {pr.state}. Nothing to review.", (), None)
        if pr.is_draft:
            return ReviewOutcome(f"Skipped: PR #{pr.number} is a draft. Nothing to review.", (), None)
        with self._repository.checkout(pr) as workspace:
            return self._agent.review(
                ReviewJob(pr, self._platform, workspace, post_comments, post_summary)
            )
