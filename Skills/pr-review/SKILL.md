---
name: pr-review
description: Review a GitHub pull request for high-signal bugs and violations of the repo's agent/contributor instructions (AGENTS.md, CLAUDE.md, etc.). Optionally posts inline review comments with the gh CLI. Use when asked to code review, check, or audit a PR.
---

# PR Review

Provide a high-signal code review for a given pull request. Prefer silence over false positives.

## Inputs

- A pull request number or URL.
- Optional `--comment`: if present, post the results to GitHub. If absent, print findings to the terminal/chat only and never post to GitHub.

## Requirements

- `gh` CLI, authenticated, with access to the repo. Use it for everything GitHub-related (viewing PRs, diffs, comments, posting). Do not scrape web pages.
- Read access to the repository checkout (for instruction files).
- Sub-agent support is optional. If the agent runtime can run parallel sub-agents, use them where noted. Otherwise run the same passes sequentially yourself. Wherever a model tier is mentioned, use the cheapest model for mechanical checks and the strongest available model for bug and logic analysis.

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
- This reviewer has already left a review on the PR. Check `gh pr view <PR> --comments` for the marker `<!-- agent-code-review -->` (every comment this skill posts must include it) or for comments by the account you post as.

Note: PRs authored by AI agents are still reviewed.

### 2. Gather repository context before assessing code (cheap model)

Before assessing the PR's implementation, gather the repository context that defines its intended behavior. This step is mandatory and must happen before any bug or instruction-compliance pass. Return file paths for:

- Root-level instruction files, if they exist: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTRIBUTING.md`, `.cursor/rules/*`, `.github/copilot-instructions.md`.
- Any such files in directories that contain files modified by the PR (and parent directories up to the root).
- The README or other project documentation relevant to the changed area.
- The existing implementation, tests, configuration, interfaces, and nearby call sites needed to understand the behavior changed by the PR.

Read the applicable instruction files and the relevant repository context before reviewing the current code. An instruction file only applies to files in its own directory or below. Do not assess the diff in isolation.

### 3. Summarize the change (mid-tier model)

View the PR (`gh pr view`, `gh pr diff`) and return a short summary of what changed and why.

### 4. Independent review passes (run in parallel if possible)

Each pass returns a list of issues. Each issue has a description, the file and line, and the reason flagged (e.g. "instruction violation", "bug").

- **Passes 1 and 2 – instruction compliance (mid-tier model).** Audit the changes against the applicable instruction files from step 2. Only flag clear, unambiguous violations where you can quote the exact rule being broken.
- **Pass 3 – shallow bug scan (strongest model).** Review the diff together with the repository context gathered in step 2. Look for significant regressions and incorrect assumptions about existing contracts, interfaces, data flow, or user-visible behavior.
- **Pass 4 – introduced-problem scan (strongest model).** Look for problems in the newly introduced code: security issues, incorrect logic, edge cases, and behavior that can appear broken to users even when it does not crash or break production outright. Stay within the changed behavior and use repository context to distinguish a real issue from a subjective improvement.

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

Drop every issue that was not validated. What remains is the final list.

**False positives (never flag these):**

- Pre-existing issues not introduced by the PR.
- Something that looks like a bug but is actually correct.
- Pedantic nitpicks a senior engineer would not raise.
- Issues a linter or type checker would catch (do not run the linter to verify).
- General quality concerns (missing tests, general security hygiene) unless an instruction file explicitly requires them or the omission creates a concrete, repository-evidenced behavioral bug.
- Issues an instruction file mentions but that are explicitly silenced in the code (e.g. a lint-ignore comment).

### 7. Report to the terminal

- If issues were found, list each with a brief description, file and line.
- If none: `No issues found. Checked for bugs and instruction-file compliance.`

If `--comment` was NOT provided, stop here. Do not post anything to GitHub.

### 8. Post to GitHub (only with `--comment`)

If no issues were found, post one summary comment and stop:

```
gh pr comment <PR> --body $'### Code review\n\nNo issues found. Checked for bugs and instruction-file compliance.\n\n<!-- agent-code-review -->'
```

If issues were found:

1. Draft the full list of comments for yourself first, to confirm you stand behind each one. Do not post this list.
2. Post one inline review comment per unique issue. Never post duplicates. Use the GitHub API, e.g.:

```
gh api repos/{owner}/{repo}/pulls/{number}/comments \
  -f body="$BODY" -f commit_id="$HEAD_SHA" -f path="$FILE" \
  -F line=$LINE -f side=RIGHT
```

   (Get `$HEAD_SHA` from `gh pr view <PR> --json headRefOid -q .headRefOid`. For multi-line ranges also pass `-F start_line=$START -f start_side=RIGHT`. If your environment offers a dedicated inline-comment tool, use that instead.)
3. Each comment contains: a brief description of the issue, a citation/link for the evidence (see link format below, and a link to the instruction file for rule violations), and the `<!-- agent-code-review -->` marker.
4. Suggestion blocks: for small, self-contained fixes include a committable GitHub suggestion block. For larger fixes (6+ lines, structural changes, or changes spanning several locations) describe the problem and the fix without a suggestion block. Never include a committable suggestion unless committing it fixes the issue entirely; if follow-up steps are needed, do not use one.

## Link format for code references

Comments are rendered as Markdown, so links must be exact:

```
https://github.com/<owner>/<repo>/blob/<full-40-char-sha>/<path>#L<start>-L<end>
```

- Use the full commit SHA. Shell substitutions such as `$(git rev-parse HEAD)` will not be expanded in a posted comment, so resolve the SHA first and paste the literal value.
- The repo must be the one being reviewed.
- Use `#` after the file name and `L<start>-L<end>` for the range.
- Include at least one line of context before and after the line you are discussing (to comment on lines 5-6, link `L4-L7`).

## Notes

- Use the `gh` CLI for all GitHub interaction.
- Every issue you post must cite and link its evidence.
- Output is only the findings. Do not narrate your process to the PR.