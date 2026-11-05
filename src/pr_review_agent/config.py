from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"
DEFAULT_THINKING = "medium"
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class Settings:
    model: str
    thinking: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        model = env.get("PR_REVIEW_MODEL") or DEFAULT_MODEL
        thinking = env.get("PR_REVIEW_THINKING") or DEFAULT_THINKING
        if thinking not in THINKING_LEVELS:
            raise ConfigError(
                f"PR_REVIEW_THINKING must be one of {', '.join(THINKING_LEVELS)}; got {thinking!r}"
            )
        return cls(model=model, thinking=thinking)


def load_dotenv(path: Path, env: MutableMapping[str, str]) -> None:
    """Load KEY=VALUE lines from `path` into `env`; existing non-empty variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value and not env.get(key):
            env[key] = value


# The agent's own checkout (src/pr_review_agent/config.py -> repo root).
AGENT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
