import io
from contextlib import contextmanager
from dataclasses import replace

from pr_review_agent.application.watch_service import WatchService
from pr_review_agent.domain.models import Platform, PrState, PullRequest, ReviewOutcome
from pr_review_agent.errors import AgentError, PlatformError


def make_pr(number: int, head: str = "a" * 40, draft: bool = False) -> PullRequest:
    return PullRequest(
        number, f"title {number}", "", "bob", PrState.OPEN, draft, "f", "main", head, "b",
        f"https://x/pull/{number}", "rh", "rb",
    )


class FakePlatform:
    platform = Platform.GITHUB

    def __init__(self, pr):
        self.pr = pr

    def get_pull_request(self):
        return self.pr


class FakeSource:
    platform = Platform.GITHUB

    def __init__(self, prs):
        self.prs = prs
        self.list_error: Exception | None = None

    def list_open_pull_requests(self):
        if self.list_error:
            raise self.list_error
        return list(self.prs)

    def pull_request(self, number):
        return FakePlatform(next(p for p in self.prs if p.number == number))


class FakeRepo:
    @contextmanager
    def checkout(self, pr):
        yield "ws"


class FakeAgent:
    def __init__(self):
        self.jobs = []
        self.urls: dict[int, tuple[str, ...]] = {}
        self.fail: set[int] = set()

    def review(self, job):
        self.jobs.append(job)
        if job.pr.number in self.fail:
            raise AgentError("boom")
        return ReviewOutcome("r", self.urls.get(job.pr.number, ()), job.pr.head_sha)


class FakeState:
    def __init__(self):
        self.heads: dict[int, str] = {}
        self.retained: list[set[int]] = []

    def last_reviewed(self, number):
        return self.heads.get(number)

    def record(self, number, head_sha):
        self.heads[number] = head_sha

    def retain(self, open_numbers):
        self.retained.append(set(open_numbers))
        self.heads = {n: h for n, h in self.heads.items() if n in open_numbers}


def make(prs):
    source, agent, state = FakeSource(prs), FakeAgent(), FakeState()
    out, err = io.StringIO(), io.StringIO()
    service = WatchService(source, FakeRepo(), agent, state, out, err, 60)
    return service, source, agent, state, out, err


def test_new_pr_is_reviewed_without_summary_recorded_and_reported():
    service, _, agent, state, out, err = make([make_pr(3)])
    service.run_once()
    job = agent.jobs[0]
    assert job.post_comments is True and job.post_summary is False
    assert state.heads == {3: "a" * 40}
    assert out.getvalue() == "✓ PR #3 no new issues · https://x/pull/3\n"
    assert "→ PR #3 title 3 @ aaaaaaa" in err.getvalue()


def test_posted_comments_are_counted():
    service, _, agent, _, out, _ = make([make_pr(3)])
    agent.urls[3] = ("u1", "u2")
    service.run_once()
    assert out.getvalue() == "✎ PR #3 posted 2 comment(s) · https://x/pull/3\n"


def test_unchanged_head_is_not_reviewed_again_but_new_head_is():
    service, source, agent, _, _, _ = make([make_pr(3)])
    service.run_once()
    service.run_once()
    assert len(agent.jobs) == 1
    source.prs = [make_pr(3, head="c" * 40)]
    service.run_once()
    assert len(agent.jobs) == 2 and agent.jobs[1].pr.head_sha == "c" * 40


def test_draft_is_not_reviewed_or_recorded_until_ready():
    service, source, agent, state, out, _ = make([make_pr(3, draft=True)])
    service.run_once()
    assert agent.jobs == [] and state.heads == {} and out.getvalue() == ""
    source.prs = [replace(source.prs[0], is_draft=False)]
    service.run_once()
    assert len(agent.jobs) == 1


def test_agent_failure_does_not_block_other_prs_and_is_retried():
    service, _, agent, state, out, err = make([make_pr(4), make_pr(3)])
    agent.fail.add(3)
    service.run_once()
    assert "✗ PR #3 failed: boom" in err.getvalue()
    assert [j.pr.number for j in agent.jobs] == [3, 4]
    assert state.heads == {4: "a" * 40}
    agent.fail.clear()
    service.run_once()
    assert [j.pr.number for j in agent.jobs] == [3, 4, 3]


def test_listing_failure_is_reported_not_raised():
    service, source, agent, state, _, err = make([make_pr(3)])
    source.list_error = PlatformError("down")
    service.run_once()
    assert err.getvalue() == "poll failed: down\n"
    assert agent.jobs == [] and state.retained == []


def test_closed_prs_are_pruned_so_reopening_triggers_review():
    service, source, agent, state, _, _ = make([make_pr(3), make_pr(4)])
    service.run_once()
    source.prs = [make_pr(4)]
    service.run_once()
    assert state.retained == [{3, 4}, {4}]
    source.prs = [make_pr(3), make_pr(4)]
    service.run_once()
    assert [j.pr.number for j in agent.jobs] == [3, 4, 3]


def test_gate_skip_since_listing_records_and_prints_nothing():
    service, source, agent, state, out, _ = make([make_pr(3)])
    # Listing says open and ready, but the fresh fetch says it was closed meanwhile.
    source.pull_request = lambda n: FakePlatform(replace(make_pr(3), state=PrState.CLOSED))
    service.run_once()
    assert agent.jobs == [] and state.heads == {} and out.getvalue() == ""
