# CLI-PR-Review-Agent

Terminal CLI that reviews pull requests with an [OMP](https://github.com/can1357/oh-my-pi) agent. The agent always runs this repo's `Skills/pr-review/SKILL.md` skill. GitHub (github.com) and Azure DevOps are supported through adapters.

Two modes:

- **One-shot** (`--pr`): review a single PR, print the findings, optionally post them.
- **Watch** (`--watch`): keep polling a repository for open PRs, review each new or updated PR, and post the comments on the PR automatically.

## Installation

### Prerequisites

| Requirement | Notes |
|---|---|
| Python >= 3.11 | |
| [`uv`](https://docs.astral.sh/uv/) | Installs and runs the tool. |
| `git` | Used to fetch and check out PR commits. |
| `omp` (oh-my-pi) on `PATH` | Must be logged in to your model provider. Check with `omp --version`. |
| A platform token | GitHub token or Azure DevOps PAT (see [Environment](#environment)). |

### Steps

```bash
git clone <this repo> CLI-PR-Review-Agent
cd CLI-PR-Review-Agent

# Recommended: editable global install, so `pr-review` works from any directory
# and picks up this checkout's .env.
uv tool install --editable .

# Configure credentials
cp .env.example .env      # then edit .env and fill in your token(s)

# Verify
pr-review --help
```

Alternatives:

- Run without installing: `uv sync`, then `uv run pr-review ...` from the repo root.
- `uv tool install .` (non-editable) works, but the installed copy cannot see this checkout's `.env`; export the variables in your shell instead.
- Update after pulling changes: editable installs update automatically; for a regular install run `uv tool install --reinstall .`.
- Uninstall: `uv tool uninstall pr-review-agent`.

## Usage

Run from a local clone of the repository that owns the PR(s). The remote URL (default `origin`) decides which GitHub/Azure repository is used.

```bash
# One-shot: print findings only (nothing is posted)
pr-review --adapter github --pr 123

# One-shot: by URL, and post findings to the PR
pr-review --adapter github --pr https://github.com/acme/widgets/pull/123 --comment

# One-shot on Azure DevOps
pr-review --adapter azure --pr 456 --comment

# Watch mode: review and post on every open PR, poll every 60s
pr-review --adapter github --watch

# Watch mode: poll every 2 minutes, different clone and remote
pr-review --adapter azure --watch --interval 120 --repo ~/src/service --remote upstream
```

### Commands and flags

| Flag | Required | What it does |
|---|---|---|
| `--adapter {github,azure}` | yes | Selects the platform. `github` supports github.com remotes only. |
| `--pr <number-or-url>` | one of `--pr` / `--watch` | One-shot mode: review this PR. A URL must point at the same repository as the remote. Mutually exclusive with `--watch`. |
| `--watch` | one of `--pr` / `--watch` | Watch mode: poll for open PRs and post reviews until stopped. Mutually exclusive with `--pr`. |
| `--interval <seconds>` | no | Seconds between polls in watch mode. Default `60`, minimum `10`. |
| `--comment` | no | One-shot only: post findings to the PR (inline comments, plus a "No issues found" summary when clean). Without it, nothing is posted. Watch mode always posts, so this flag has no effect there. |
| `--repo <path>` | no | Local clone of the PR's repository. Default `.`. |
| `--remote <name>` | no | Git remote of that repository. Default `origin`. |
| `--help` | no | Show the argument summary. |

Argument errors (neither/both of `--pr` and `--watch`, `--interval` below 10) exit with code 2.

### One-shot mode

1. Fetches the PR and skips it if it is merged, closed, or a draft.
2. Checks the PR head out into a temporary detached git worktree (removed afterwards).
3. Runs the agent with the pr-review skill; the report goes to **stdout**.
4. With `--comment`, posts one inline comment per issue, or a single summary comment if there are no issues (skipped if a review marker comment already exists).

Progress (`· tool_name` lines) and the header line go to **stderr**.

### Watch mode

```bash
pr-review --adapter github --watch
```

- On start it reviews every open, non-draft PR (the existing backlog), then re-polls every `--interval` seconds.
- A PR is reviewed when it first appears and again whenever its head commit changes. Drafts are ignored until marked ready.
- Reviews run one at a time. Findings are posted directly on the PR as inline comments.
- A clean review posts **nothing** on the PR; the CLI prints a short line instead.
- Output lines (stdout unless noted):

| Line | Meaning |
|---|---|
| `→ PR #n <title> @ <sha7>` (stderr) | Review started. |
| `✎ PR #n posted k comment(s) · <url>` | Review posted `k` comments. |
| `✓ PR #n no new issues · <url>` | Review finished, nothing posted. |
| `✗ PR #n failed: <reason>` (stderr) | Review failed; retried on the next poll. |
| `poll failed: <reason>` (stderr) | Listing PRs failed; retried on the next poll. |

- **Persistence:** last-reviewed head SHAs are stored in `$XDG_STATE_HOME/pr-review/<platform>-<hash>.json` (default `~/.local/state/pr-review/`), one file per remote. Restarts do not re-review unchanged PRs. PRs that close or merge are dropped from the file, so a reopened PR is reviewed again. If the file is corrupt or belongs to another remote, the CLI exits with an error; delete the file to start over.
- **Stop:** Ctrl-C prints `stopped` and exits `0`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (watch mode: stopped with Ctrl-C). |
| `1` | Platform, git, or agent failure (one-shot). |
| `2` | Configuration or argument error (missing token, `omp` not on `PATH`, bad `--interval`, corrupt watch state, ...). |
| `130` | One-shot interrupted with Ctrl-C. |

## Environment

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub token (`--adapter github`). Classic token: `repo` scope. Fine-grained: Pull requests read/write + Contents read. |
| `AZURE_DEVOPS_PAT` | Azure DevOps PAT with Code: Read & Write (`--adapter azure`). |
| `PR_REVIEW_MODEL` | Model, default `anthropic/claude-sonnet-5-5`. |
| `PR_REVIEW_THINKING` | `off\|minimal\|low\|medium\|high\|xhigh\|max`, default `medium`. |
| `XDG_STATE_HOME` | Base directory for watch state, default `~/.local/state`. |

`pr-review` loads `.env` from this repository's root (git-ignored) on every run, from whatever directory you run it. Variables already set in your shell take precedence; blank values are ignored. This is why the editable install is recommended.

Platform credentials are blanked in the agent's subprocess environment, so the agent's shell cannot read them.

## How it works

The agent gets read-only tools (`read`, `grep`, `glob`, `bash`, `task`, `todo`) in the PR checkout, plus platform tools provided by the CLI:

| Tool | Purpose |
|---|---|
| `pr_get` | PR metadata and the account comments are posted as. |
| `pr_changed_files` | Changed paths with status. |
| `pr_diff` | Unified diff (optionally one file). |
| `pr_comments` | Existing comments, used to avoid duplicates. |
| `pr_file_link` | Permalink for a line range at the PR head. |
| `pr_post_inline_comment` | Inline comment (only with `--comment`, always in watch mode). |
| `pr_post_summary_comment` | PR-level summary (only with `--comment` in one-shot; withheld in watch mode). |

Every posted comment carries the `<!-- agent-code-review -->` marker; duplicates within a run are dropped.

Layout: `domain` (models) ← `ports` (protocols) ← `application` (`ReviewService`, `WatchService`); `adapters` implement ports (GitHub, Azure DevOps, git workspace, OMP agent, JSON watch state); only `cli.py` wires concrete adapters.

## Development

```bash
uv sync
uv run pytest -q
```
