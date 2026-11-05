import json
import threading
from dataclasses import asdict
from typing import Any, TextIO, cast

from omp_rpc import HostTool, RpcClient, RpcError, host_tool

from ..config import Settings
from ..domain.models import InlineComment, ensure_marker
from ..errors import AgentError
from ..ports.agent import ReviewJob
from ..skill import load_skill_text

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
_DUP_SUMMARY = "Duplicate: a summary comment was already posted in this run; not posted again."
_DUP_INLINE = "Duplicate: identical comment already posted in this run; not posted again."


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def build_host_tools(job: ReviewJob) -> list[HostTool[Any, Any]]:
    """Platform tools exposed to the agent. Calls arrive on parallel threads."""
    lock = threading.Lock()
    cache: dict[str, Any] = {}
    posted_inline: set[tuple[str, int, int | None, str]] = set()
    summary_posted = False

    def cached(key: str, fn: Any) -> Any:
        with lock:
            if key not in cache:
                cache[key] = fn()
            return cache[key]

    def changed_files() -> list[Any]:
        return cached("changed_files", job.workspace.changed_files)

    def pr_get(args: dict, ctx: Any) -> str:
        account = cached("account", job.platform.get_authenticated_account)
        data = asdict(job.pr)
        data["platform"] = job.platform.platform.value
        data["reviewer_account"] = {"id": account.id, "name": account.name}
        return _json(data)

    def pr_changed_files(args: dict, ctx: Any) -> str:
        return _json([asdict(f) for f in changed_files()])

    def pr_diff(args: dict, ctx: Any) -> str:
        path = args.get("path")
        text = job.workspace.diff(path)
        if not text.strip():
            return f"No changes for {path}." if path else "Empty diff."
        return text

    def pr_comments(args: dict, ctx: Any) -> str:
        return _json([asdict(c) for c in job.platform.list_comments()])

    def pr_file_link(args: dict, ctx: Any) -> str:
        start, end = args["start_line"], args["end_line"]
        if start > end:
            raise ValueError("start_line must be <= end_line")
        return job.platform.file_link(job.pr, args["path"], start, end)

    def pr_post_summary_comment(args: dict, ctx: Any) -> str:
        nonlocal summary_posted
        with lock:
            if summary_posted:
                return _DUP_SUMMARY
            url = job.platform.post_summary_comment(ensure_marker(args["body"]))
            summary_posted = True
        return url

    def pr_post_inline_comment(args: dict, ctx: Any) -> str:
        path, line = args["path"], args["line"]
        start_line, body = args.get("start_line"), args["body"]
        if path not in {f.path for f in changed_files()}:
            raise ValueError(f"{path} is not changed in this PR")
        key = (path, line, start_line, body)
        with lock:
            if key in posted_inline:
                return _DUP_INLINE
            url = job.platform.post_inline_comment(
                job.pr, InlineComment(path, line, start_line, ensure_marker(body))
            )
            posted_inline.add(key)
        return url

    def tool(name: str, description: str, parameters: dict[str, Any], execute: Any) -> HostTool:
        return host_tool(
            name=name,
            description=description,
            parameters=parameters,
            execute=execute,
            load_mode="essential",
        )

    positive_int = {"type": "integer", "minimum": 1}
    tools = [
        tool(
            "pr_get",
            "PR metadata (title, description, author, state, draft, branches, head/base SHA, URL) "
            "and reviewer_account: the account comments are posted as.",
            _NO_ARGS,
            pr_get,
        ),
        tool("pr_changed_files", "Changed paths of the PR with status.", _NO_ARGS, pr_changed_files),
        tool(
            "pr_diff",
            "Unified diff of the PR. Optional path limits it to one file.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "additionalProperties": False,
            },
            pr_diff,
        ),
        tool(
            "pr_comments",
            "Every existing comment on the PR (author id/name, body, file, line).",
            _NO_ARGS,
            pr_comments,
        ),
        tool(
            "pr_file_link",
            "Exact permalink for a file line range at the PR head commit. "
            "Always use this for links in comments.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": positive_int,
                    "end_line": positive_int,
                },
                "required": ["path", "start_line", "end_line"],
                "additionalProperties": False,
            },
            pr_file_link,
        ),
    ]
    if job.post_comments:
        tools += [
            tool(
                "pr_post_summary_comment",
                "Post one PR-level summary comment. The review marker is added automatically.",
                {
                    "type": "object",
                    "properties": {"body": {"type": "string"}},
                    "required": ["body"],
                    "additionalProperties": False,
                },
                pr_post_summary_comment,
            ),
            tool(
                "pr_post_inline_comment",
                "Post an inline review comment on the new side of the diff at the PR head "
                "commit. start_line is only for multi-line ranges. The review marker is "
                "added automatically.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "line": positive_int,
                        "start_line": positive_int,
                        "body": {"type": "string"},
                    },
                    "required": ["path", "line", "body"],
                    "additionalProperties": False,
                },
                pr_post_inline_comment,
            ),
        ]
    return tools


def _run_context(job: ReviewJob) -> str:
    pr = job.pr
    comment_line = (
        "provided — posting tools are available"
        if job.post_comments
        else "NOT provided — posting tools are not available; never post"
    )
    return "\n".join(
        [
            "## Run context",
            f"- Platform: {job.platform.platform.display_name}",
            f"- Pull request: #{pr.number} {pr.web_url}",
            f"- Working directory: detached checkout of PR head {pr.head_sha} "
            f"(base {pr.base_sha}). Do not modify files; use bash only to run the repository's existing test suite (Step 4, Pass 5).",
            f"- --comment: {comment_line}",
            "- Execute every skill step in order. Step 2 is mandatory even for small PRs: "
            "never report that no issues were found without having read the applicable "
            "instruction files from the checkout.",
            "- Your final message is printed verbatim to the user's terminal; it must contain "
            "only the Step 7 report (or one line saying why the review stopped at Step 1).",
        ]
    )


class OmpReviewAgent:
    def __init__(self, settings: Settings, progress: TextIO) -> None:
        self._settings = settings
        self._progress = progress

    def review(self, job: ReviewJob) -> str:
        pr = job.pr
        system_append = load_skill_text() + "\n\n" + _run_context(job)
        client = RpcClient(
            model=self._settings.model,
            thinking=cast(Any, self._settings.thinking),
            cwd=job.workspace.root,
            tools=("read", "grep", "glob", "bash", "task", "todo"),
            # bash runs in a child process: keep platform credentials out of it.
            env={"GITHUB_TOKEN": "", "GH_TOKEN": "", "AZURE_DEVOPS_PAT": ""},
            custom_tools=build_host_tools(job),
            append_system_prompt=system_append,
            no_session=True,
            no_skills=True,
            no_rules=True,
            no_ui=True,
            extra_args=("--no-context-files", "--no-lsp", "--approval-mode", "yolo"),
            startup_timeout=60.0,
        )
        with client:
            client.install_headless_ui()
            client.on_tool_execution_start(
                lambda e: print(f"  · {e.tool_name}", file=self._progress, flush=True)
            )
            prompt = (
                f"Review pull request #{pr.number} ({pr.web_url}) following the pr-review skill. "
                f"--comment is {'provided' if job.post_comments else 'not provided'}."
            )
            turn = client.prompt_and_wait(prompt)
        result = turn.result
        if result is not None and result.status == "error":
            message = result.error.message if result.error else "unknown error"
            raise AgentError(f"agent failed: {message}")
        if result is not None and result.status == "aborted":
            raise AgentError("agent run was aborted")
        try:
            return turn.require_assistant_text().strip()
        except RpcError as exc:
            raise AgentError("agent finished without a report") from exc
