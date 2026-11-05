from typing import Protocol


class WatchStatePort(Protocol):
    def last_reviewed(self, number: int) -> str | None: ...

    def record(self, number: int, head_sha: str) -> None: ...

    def retain(self, open_numbers: set[int]) -> None:
        """Forget every PR number not in `open_numbers`."""
        ...
