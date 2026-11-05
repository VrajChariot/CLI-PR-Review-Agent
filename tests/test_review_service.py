from contextlib import contextmanager

import pytest

from pr_review_agent.application.review_service import ReviewService
from pr_review_agent.domain.models import Platform, PrState, PullRequest


def make_pr(state=PrState.OPEN, draft=False) -> PullRequest:
    return PullRequest(5, "t", "", "a", state, draft, "f", "main", "h", "b", "u", "rh", "rb")


class FakePlatform:
    platform = Platform.GITHUB

    def __init__(self, pr):
        self.pr = pr

    def get_pull_request(self):
        return self.pr


class FakeRepo:
    def __init__(self):
        self.checkouts = 0

    @contextmanager
    def checkout(self, pr):
        self.checkouts += 1
        yield "ws"


class FakeAgent:
    def __init__(self):
        self.jobs = []

    def review(self, job):
        self.jobs.append(job)
        return "report"


@pytest.mark.parametrize(
    "pr,text",
    [
        (make_pr(PrState.MERGED), "Skipped: PR #5 is merged. Nothing to review."),
        (make_pr(PrState.CLOSED), "Skipped: PR #5 is closed. Nothing to review."),
        (make_pr(draft=True), "Skipped: PR #5 is a draft. Nothing to review."),
    ],
)
def test_ineligible_prs_skip_checkout_and_agent(pr, text):
    repo, agent = FakeRepo(), FakeAgent()
    assert ReviewService(FakePlatform(pr), repo, agent).run(False) == text
    assert repo.checkouts == 0 and agent.jobs == []


def test_open_pr_is_reviewed():
    repo, agent = FakeRepo(), FakeAgent()
    out = ReviewService(FakePlatform(make_pr()), repo, agent).run(True)
    assert out == "report"
    assert repo.checkouts == 1
    assert agent.jobs[0].post_comments is True and agent.jobs[0].workspace == "ws"
