import argparse
import os
import shutil
import sys
from pathlib import Path

from .adapters.azure_devops import azure_from_args, azure_repository_from_remote
from .adapters.git_workspace import GitRepository
from .adapters.github import github_from_args, github_repository_from_remote
from .adapters.omp_agent import OmpReviewAgent
from .adapters.watch_state import JsonWatchState, default_state_path
from .application.review_service import ReviewService
from .application.watch_service import WatchService
from .config import AGENT_ENV_FILE, Settings, load_dotenv
from .errors import AgentError, ConfigError, PlatformError, WorkspaceError

_FACTORIES = {"github": github_from_args, "azure": azure_from_args}
_SOURCE_FACTORIES = {
    "github": github_repository_from_remote,
    "azure": azure_repository_from_remote,
}
_MIN_INTERVAL = 10


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pr-review",
        description="Review a pull request with an OMP agent following the pr-review skill.",
    )
    p.add_argument(
        "--adapter", required=True, choices=sorted(_FACTORIES), help="Platform adapter to use"
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pr", help="PR number or PR URL")
    mode.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling for open PRs and post reviews to them",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between polls in --watch mode",
    )
    p.add_argument(
        "--comment",
        action="store_true",
        help="Post findings to the PR; default prints only (--watch always posts)",
    )
    p.add_argument("--repo", default=".", help="Local clone of the PR's repository")
    p.add_argument("--remote", default="origin", help="Git remote of the PR's repository")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.interval < _MIN_INTERVAL:
        parser.error(f"--interval must be at least {_MIN_INTERVAL} seconds")
    load_dotenv(AGENT_ENV_FILE, os.environ)
    try:
        settings = Settings.from_env(os.environ)
        if shutil.which("omp") is None:
            raise ConfigError("omp executable not found on PATH; install oh-my-pi")
        repo = GitRepository(Path(args.repo), args.remote)
        agent = OmpReviewAgent(settings, sys.stderr)
        remote_url = repo.remote_url()
        if args.watch:
            source = _SOURCE_FACTORIES[args.adapter](remote_url, os.environ)
            state = JsonWatchState(
                default_state_path(source.platform, remote_url, os.environ), remote_url
            )
            print(
                f"pr-review: watching {remote_url} on {source.platform.display_name} "
                f"every {args.interval}s · model {settings.model} · thinking {settings.thinking}",
                file=sys.stderr,
            )
            WatchService(
                source, repo, agent, state, sys.stdout, sys.stderr, args.interval
            ).run_forever()
            return 0
        platform = _FACTORIES[args.adapter](remote_url, args.pr, os.environ)
        service = ReviewService(platform, repo, agent)
        print(
            f"pr-review: {platform.platform.display_name} · model {settings.model} "
            f"· thinking {settings.thinking}",
            file=sys.stderr,
        )
        print(service.run(post_comments=args.comment).report)
        return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (PlatformError, WorkspaceError, AgentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if args.watch:
            print("stopped", file=sys.stderr)
            return 0
        print("interrupted", file=sys.stderr)
        return 130
