"""Export current Git-visible files without committing or modifying the index."""
from pathlib import Path
import shutil
import subprocess


AUTOMATIC_AGENT_INSTRUCTION_NAMES = {
    ".clinerules",
    ".cursorrules",
    ".windsurfrules",
    "agents.md",
    "agents.override.md",
    "claude.md",
    "gemini.md",
}


def is_automatic_agent_instruction(relative: Path) -> bool:
    """Return whether an installed checkout could auto-load this as agent policy."""
    lowered = tuple(part.casefold() for part in relative.parts)
    if relative.name.casefold() in AUTOMATIC_AGENT_INSTRUCTION_NAMES:
        return True
    if lowered == (".github", "copilot-instructions.md"):
        return True
    return (
        len(lowered) >= 3
        and lowered[0:2] == (".github", "instructions")
        and lowered[-1].endswith(".instructions.md")
    )


def export_source(root: Path, destination: Path) -> list[Path]:
    """Include unstaged/new source, exclude ignored files, reject unsafe content."""
    root = root.resolve()
    if destination.exists():
        raise ValueError("Snapshot destination must not exist")
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--deduplicate"],
        cwd=root).decode().split("\0")
    paths = []
    for name in filter(None, names):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe repository path")
        if is_automatic_agent_instruction(relative):
            raise ValueError(
                f"Automatic agent instruction file cannot be published: {relative}"
            )
        path = root / relative
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
            raise ValueError(f"Symlink cannot be published: {relative}")
        if not path.exists():  # Unstaged deletion.
            continue
        if not path.is_file():
            raise ValueError(f"Not a regular file: {relative}")
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", name], cwd=root)
        if ignored.returncode == 0:
            raise ValueError(f"Tracked ignored file: {relative}; remove it from the index first")
        if ignored.returncode != 1:
            raise ValueError("Cannot inspect ignore rules")
        paths.append(relative)
    destination.mkdir(parents=True)
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    return paths
