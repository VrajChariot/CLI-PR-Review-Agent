import argparse
import os
import shutil
import sys
from pathlib import Path

from .adapters.azure_devops import azure_from_args
from .adapters.git_workspace import GitRepository
from .adapters.github import github_from_args
from .adapters.omp_agent import OmpReviewAgent
from .application.review_service import ReviewService
from .config import AGENT_ENV_FILE, Settings, load_dotenv
from .errors import AgentError, ConfigError, PlatformError, WorkspaceError

_FACTORIES = {"github": github_from_args, "azure": azure_from_args}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pr-review",
        description="Review a pull request with an OMP agent following the pr-review skill.",
    )
    p.add_argument(
        "--adapter", required=True, choices=sorted(_FACTORIES), help="Platform adapter to use"
    )
    p.add_argument("--pr", required=True, help="PR number or PR URL")
    p.add_argument(
        "--comment",
        action="store_true",
        help="Post findings to the PR; default prints only",
    )
    p.add_argument("--repo", default=".", help="Local clone of the PR's repository")
    p.add_argument("--remote", default="origin", help="Git remote of the PR's repository")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(AGENT_ENV_FILE, os.environ)
    try:
        settings = Settings.from_env(os.environ)
        if shutil.which("omp") is None:
            raise ConfigError("omp executable not found on PATH; install oh-my-pi")
        repo = GitRepository(Path(args.repo), args.remote)
        platform = _FACTORIES[args.adapter](repo.remote_url(), args.pr, os.environ)
        service = ReviewService(platform, repo, OmpReviewAgent(settings, sys.stderr))
        print(
            f"pr-review: {platform.platform.display_name} · model {settings.model} "
            f"· thinking {settings.thinking}",
            file=sys.stderr,
        )
        print(service.run(post_comments=args.comment))
        return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (PlatformError, WorkspaceError, AgentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
