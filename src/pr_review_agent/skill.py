from importlib import resources
from pathlib import Path

from .errors import ConfigError

_HEADER = "# Skill: pr-review (always active — follow it exactly for this review)\n\n"


def _candidates() -> list[Path]:
    packaged = resources.files("pr_review_agent") / "skills" / "pr-review" / "SKILL.md"
    checkout = Path(__file__).resolve().parents[2] / "Skills" / "pr-review" / "SKILL.md"
    return [Path(str(packaged)), checkout]


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :])
    return text


def load_skill_text() -> str:
    for path in _candidates():
        if path.is_file():
            return _HEADER + _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    raise ConfigError("pr-review skill not found (expected Skills/pr-review/SKILL.md)")
