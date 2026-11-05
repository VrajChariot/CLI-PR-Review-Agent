from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from ..domain.models import ChangedFile, PullRequest


class ReviewWorkspace(Protocol):
    root: Path

    def diff(self, path: str | None = None) -> str: ...

    def changed_files(self) -> list[ChangedFile]: ...


class RepositoryPort(Protocol):
    def remote_url(self) -> str: ...

    def checkout(self, pr: PullRequest) -> AbstractContextManager[ReviewWorkspace]: ...
