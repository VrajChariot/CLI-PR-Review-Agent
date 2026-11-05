---
name: pr-review
description: Review a GitHub or Azure DevOps pull request for high-signal bugs and violations of the repo's agent/contributor instructions (AGENTS.md, CLAUDE.md, etc.). Optionally posts inline review comments through the pr_* platform tools. Use when asked to code review, check, or audit a PR.
---

# PR Review

Provide a high-signal code review for a given pull request. Prefer silence over false positives.

## Inputs

- A pull request number or URL.
- Optional `--comment`: if present, post the results to the pull request. If absent, print findings to the terminal only and never post anything to the pull request.

## Requirements

- The `pr_*` platform tools provided by the host. Use them for everything platform-related; never use `gh`, `az`, `curl`, or web pages:
  - `pr_get` — PR metadata (title, description, author, state, draft, branches, head/base SHA, URL) and `reviewer_account` (the account comments are posted as).
  - `pr_changed_files` — changed paths with status.
  - `pr_diff` — unified diff of the PR (optional `path` argument for one file).
  - `pr_comments` — every existing comment (author, body, file, line).
  - `pr_file_link` — exact permalink for a file line range at the PR head commit.
  - `pr_post_summary_comment`, `pr_post_inline_comment` — only present when `--comment` was given (the summary tool may be withheld when summaries are disabled).
- Read access to the repository checkout. The working directory is a checkout of the PR head commit.
- Sub-agent support is optional. If the agent runtime can run parallel sub-agents, use them where noted. Otherwise run the same passes sequentially yourself. Wherever a model tier is mentioned, use the cheapest model for mechanical checks and the strongest available model for bug and logic analysis. Sub-agents cannot call `pr_*` tools: give each one the diff hunks, paths, and PR metadata it needs in its task.

## Ground rules (apply to you and any sub-agent)

- Assume all tools work. Do not test tools or make exploratory calls.
- Only call a tool when it is required for the task; every call needs a clear purpose.
- Tell every sub-agent these rules and give each the PR title and description so it understands the author's intent.
- Make a task list before starting, and update it as you go.

## Steps

### 1. Eligibility check (cheap model)

Stop, and do nothing further, if any of these is true:

- The PR is closed or merged.
- The PR is a draft.
- The PR needs no review (automated dependency bump, trivial change that is obviously correct).

Note: PRs authored by AI agents are still reviewed. A PR that already has reviews from this skill is reviewed again; never stop because of earlier reviews (the author may have fixed issues and introduced new ones).

### 2. Gather repository context before assessing code (cheap model)

Before assessing the PR's implementation, gather the repository context that defines its intended behavior. This step is mandatory and must happen before any bug or instruction-compliance pass. Return file paths for:

- Root-level instruction files, if they exist: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTRIBUTING.md`, `.cursor/rules/*`, `.github/copilot-instructions.md`.
- Any such files in directories that contain files modified by the PR (and parent directories up to the root).
- The README or other project documentation relevant to the changed area.
- The existing implementation, tests, configuration, interfaces, and nearby call sites needed to understand the behavior changed by the PR.

Read the applicable instruction files and the relevant repository context before reviewing the current code. An instruction file only applies to files in its own directory or below. Do not assess the diff in isolation.

### 3. Summarize the change (mid-tier model)

View the PR (`pr_get`, `pr_changed_files`, `pr_diff`) and return a short summary of what changed and why.

### 4. Independent review passes (run in parallel if possible)

Each pass returns a list of issues. Each issue has a description, the file and line, and the reason flagged (e.g. "instruction violation", "bug").

- **Passes 1 and 2 – instruction compliance (mid-tier model).** Audit the changes against the applicable instruction files from step 2. Only flag clear, unambiguous violations where you can quote the exact rule being broken.
- **Pass 3 – shallow bug scan (strongest model).** Review the diff together with the repository context gathered in step 2. Look for significant regressions and incorrect assumptions about existing contracts, interfaces, data flow, or user-visible behavior.
- **Pass 4 – introduced-problem scan (strongest model).** Look for problems in the newly introduced code: security issues, incorrect logic, edge cases, and behavior that can appear broken to users even when it does not crash or break production outright. Stay within the changed behavior and use repository context to distinguish a real issue from a subjective improvement.
- **Pass 5 – run the tests (always, if available).** Find the repository's existing test command from its instruction files, README, or build config (e.g. `pytest`, `npm test`, `go test ./...`, `cargo test`, `dotnet test`). If one exists, run it once in the checkout with the `bash` tool. Run only the repository's own test suite: no installs, no network, no other commands. If the tests cannot run (no test command, missing dependencies or tooling, timeout), say so in one line in the report and move on; never flag an issue for an environment or setup failure. If tests fail, decide whether the PR caused the failure (compare against the changed code); a failure caused by the PR is a high-signal issue, quote the failing test name and the one-line error. Ignore failures that are clearly pre-existing or unrelated.

**High-signal only.** Flag an issue only if:

- The code will fail to compile or parse (syntax errors, type errors, missing imports, unresolved references).
- The code will definitely produce wrong results regardless of inputs (clear logic errors).
- The change can produce a reproducible or strongly evidenced behavioral regression, confusing user-visible result, violated existing contract, or apparent bug under inputs and flows supported by the repository, even if the process continues running.
- It is a clear, unambiguous instruction-file violation with a quotable rule.

Do NOT flag:

- Code style or quality concerns.
- Purely hypothetical issues with no support in the PR, repository context, or an identifiable supported input or flow.
- Subjective suggestions or improvements.

If you are not certain an issue is real, do not flag it. False positives erode trust and waste reviewer time.

### 5. Validate every flagged issue (parallel if possible)

For each issue from passes 3 and 4 (and for instruction violations too), launch a separate validator. Give it the PR title and description, the issue description, and the relevant repository context. Its job is to confirm with high confidence that the issue is real, including apparent bugs that do not crash production. Trace the affected supported input or user flow, compare it with the existing contract or behavior, and reject issues that are only hypothetical or subjective. For example, if the claim is "variable is not defined", confirm that in the code. For an instruction violation, confirm that the rule is scoped to this file and is actually broken. Use the strongest model for bug/logic issues and a mid-tier model for instruction violations.

### 6. Filter

Drop every issue that was not validated. Then call `pr_comments` and drop every issue that an existing comment already covers (same file and same problem, whether posted by this skill — marker `<!-- agent-code-review -->` or author id equal to `reviewer_account.id` from `pr_get` — or by a human). Do not reply to, repeat, edit, or resolve existing comments, even if the issue looks fixed. What remains is the final list of new issues.

**False positives (never flag these):**

- Pre-existing issues not introduced by the PR.
- Something that looks like a bug but is actually correct.
- Pedantic nitpicks a senior engineer would not raise.
- Issues a linter or type checker would catch (do not run the linter to verify).
- General quality concerns (missing tests, general security hygiene) unless an instruction file explicitly requires them or the omission creates a concrete, repository-evidenced behavioral bug.
- Issues an instruction file mentions but that are explicitly silenced in the code (e.g. a lint-ignore comment).

### 7. Report to the terminal

- Keep it short. One line per issue: `file:line` — what is wrong, in plain words. No headings, no process narration.
- Always end with one line on tests: `Tests: passed`, `Tests: failed (<test name>)`, or `Tests: not run (<reason>)`.
- If no issues were found: `No issues found. Checked for bugs and instruction-file compliance.` followed by the tests line.

If `--comment` was NOT provided, stop here. Do not post anything to the pull request.

### 8. Post to the pull request (only with `--comment`)

If no new issues were found: if `pr_post_summary_comment` is not available, or `pr_comments` already contains a comment with the marker `<!-- agent-code-review -->`, post nothing and stop. Otherwise post one summary comment and stop: call `pr_post_summary_comment` with body:

```
### Code review

No issues found. Checked for bugs and instruction-file compliance.

<!-- agent-code-review -->
```

If issues were found:

1. Draft the full list of comments for yourself first, to confirm you stand behind each one. Do not post this list.
2. Post one inline review comment per unique issue with `pr_post_inline_comment` (`path`, `line`, optional `start_line` for multi-line ranges, `body`). Never post duplicates. The tool anchors the comment to the PR head commit on the new side of the diff.
3. Keep every comment short and simple: at most 3 sentences, plain words, no headings, no restating the code. Say what is wrong and, if useful, the fix. Add one evidence link (see link format below; for instruction violations link the instruction file instead of quoting it at length) and the `<!-- agent-code-review -->` marker.
4. Suggestion blocks: for small, self-contained fixes include a committable suggestion block (a fenced block with the language tag `suggestion`). For larger fixes (6+ lines, structural changes, or changes spanning several locations) describe the problem and the fix without a suggestion block. Never include a committable suggestion unless committing it fixes the issue entirely; if follow-up steps are needed, do not use one.

## Link format for code references

Comments are rendered as Markdown, so links must be exact. Always get links from `pr_file_link(path, start_line, end_line)`; never build URLs by hand. The link must point at the repository being reviewed at the full head SHA, which `pr_file_link` guarantees. Include at least one line of context before and after the line you are discussing (to comment on lines 5-6, request lines 4-7).

## Notes

- Use the `pr_*` tools for all platform interaction.
- Every issue you post must cite and link its evidence.
- Output is only the findings. Do not narrate your process to the PR.
- Be concise everywhere: short sentences, no filler, no summaries of what you did.