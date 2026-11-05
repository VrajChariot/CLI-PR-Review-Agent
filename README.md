# CLI-PR-Review-Agent

Terminal CLI that reviews one pull request with an [OMP](https://github.com/can1357/oh-my-pi) agent. The agent always runs the repo's `Skills/pr-review/SKILL.md` skill. GitHub and Azure DevOps are supported through adapters.

## Install

Requires Python >= 3.11, `git`, and `omp` (logged in to your model provider) on `PATH`.

```
uv tool install .        # or: uv sync && uv run pr-review ...
```

## Usage

Run from a local clone of the repository that owns the PR:

```
pr-review --adapter github --pr 123            # print findings only
pr-review --adapter azure  --pr <id-or-url> --comment   # also post to the PR
```

| Flag | Meaning |
|---|---|
| `--adapter {github,azure}` | Required. Platform adapter. |
| `--pr` | Required. PR number or PR URL (must match the remote). |
| `--comment` | Post findings to the PR. Default: print only. |
| `--repo` | Local clone (default `.`). |
| `--remote` | Git remote (default `origin`). |

The report goes to stdout; progress and the header line go to stderr. Exit codes: `0` ok, `1` platform/git/agent failure, `2` configuration error, `130` interrupted.

## Environment

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub token with repo access (`--adapter github`, github.com only). |
| `AZURE_DEVOPS_PAT` | Azure DevOps PAT with Code: Read & Write (`--adapter azure`). |
| `PR_REVIEW_MODEL` | Model, default `anthropic/claude-sonnet-5-5`. |
| `PR_REVIEW_THINKING` | `off\|minimal\|low\|medium\|high\|xhigh\|max`, default `medium`. |

Copy `.env.example` to `.env` in this repository's root (git-ignored) and fill it in. `pr-review` loads it automatically on every run, from whatever directory you run it. Variables already set in your shell take precedence; blank values are ignored.

This relies on the agent running from its own checkout, so install it editable: `uv tool install --editable .` (a regular `uv tool install .` copies the code and won't see `.env`).

## How it works

The PR head is checked out into a temporary detached git worktree (removed afterwards). The agent has read-only tools plus `pr_*` platform tools (`pr_get`, `pr_changed_files`, `pr_diff`, `pr_comments`, `pr_file_link`, and with `--comment` `pr_post_summary_comment` / `pr_post_inline_comment`). Merged, closed, and draft PRs are skipped before the agent starts. Every posted comment carries the `<!-- agent-code-review -->` marker, so reruns stop at the skill's eligibility check.

Layout: `domain` (models) ← `ports` (protocols) ← `application` (service); `adapters` implement ports; only `cli.py` wires concrete adapters.
