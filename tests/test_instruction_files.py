from pathlib import Path

from pr_review_agent.adapters.instruction_files import discover_instruction_files
from pr_review_agent.domain.models import ChangedFile


def write(root: Path, rel: str, text: str = "rule") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def paths(found):
    return [f["path"] for f in found]


def test_collects_root_and_ancestor_files_of_changed_paths_only(tmp_path: Path):
    write(tmp_path, "AGENTS.md")
    write(tmp_path, "CLAUDE.md")
    write(tmp_path, ".github/copilot-instructions.md")
    write(tmp_path, ".cursor/rules/style.mdc")
    write(tmp_path, "src/api/AGENTS.md")
    write(tmp_path, "src/AGENTS.md")
    write(tmp_path, "docs/AGENTS.md")  # unrelated directory
    found = discover_instruction_files(tmp_path, [ChangedFile("src/api/x.py", "modified", None)])
    assert paths(found) == [
        "AGENTS.md",
        "CLAUDE.md",
        "src/AGENTS.md",
        "src/api/AGENTS.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/style.mdc",
    ]
    assert found[2]["applies_to"] == "src"


def test_renamed_file_old_directory_rules_still_apply(tmp_path: Path):
    write(tmp_path, "old/AGENTS.md")
    found = discover_instruction_files(
        tmp_path, [ChangedFile("new/x.py", "renamed", "old/x.py")]
    )
    assert paths(found) == ["old/AGENTS.md"]


def test_symlink_escaping_checkout_is_ignored(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").symlink_to(outside)
    assert discover_instruction_files(root, [ChangedFile("a.py", "added", None)]) == []


def test_long_file_is_truncated(tmp_path: Path):
    write(tmp_path, "AGENTS.md", "x" * 30_000)
    (f,) = discover_instruction_files(tmp_path, [ChangedFile("a.py", "added", None)])
    assert len(f["content"]) < 21_000 and "truncated" in f["content"]
