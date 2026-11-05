from pathlib import Path, PurePosixPath

from ..domain.models import ChangedFile

# Instruction files that apply to their own directory and everything below it.
_PER_DIRECTORY = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "CONTRIBUTING.md")
# Instruction files that only exist at the repository root.
_ROOT_ONLY = (".github/copilot-instructions.md",)
_ROOT_GLOBS = (".cursor/rules/*",)
MAX_FILE_CHARS = 20_000


def _read(root: Path, rel: str) -> str | None:
    path = (root / rel).resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        return None  # missing, or a symlink pointing outside the checkout
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n[truncated: read the full file from the checkout]"
    return text


def discover_instruction_files(root: Path, changed: list[ChangedFile]) -> list[dict[str, str]]:
    """Instruction files in the checkout that apply to at least one changed path.

    Deterministic, so a review can never skip a rule file by failing to look for it.
    """
    dirs: set[PurePosixPath] = {PurePosixPath(".")}
    for f in changed:
        for p in (f.path, f.old_path):
            if p:
                dirs.update(PurePosixPath(p).parents)
    candidates: list[tuple[str, str]] = []  # (relative path, scope directory)
    for d in sorted(dirs, key=lambda x: (len(x.parts), str(x))):
        for name in _PER_DIRECTORY:
            candidates.append((str(d / name) if d.parts else name, str(d)))
    root_resolved = root.resolve()
    for rel in _ROOT_ONLY:
        candidates.append((rel, "."))
    for pattern in _ROOT_GLOBS:
        for match in sorted(root_resolved.glob(pattern)):
            candidates.append((str(match.relative_to(root_resolved)), "."))
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel, scope in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        content = _read(root, rel)
        if content is not None:
            found.append({"path": rel, "applies_to": scope, "content": content})
    return found
