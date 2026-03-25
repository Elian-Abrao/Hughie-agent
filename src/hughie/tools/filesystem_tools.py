"""Filesystem tools: read, write, list, find."""

import fnmatch
from pathlib import Path

from langchain_core.tools import tool

MAX_READ = 20_000   # chars
MAX_RESULTS = 50


def _safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


@tool
def read_file(path: str) -> str:
    """Read the content of a file.

    Args:
        path: Absolute or relative path to the file
    """
    p = _safe_path(path)
    if not p.exists():
        return f"Error: file not found: {p}"
    if not p.is_file():
        return f"Error: path is not a file: {p}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_READ:
            return content[:MAX_READ] + f"\n... [truncated, {len(content)} chars total]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
async def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed.

    Always asks for user confirmation before writing.

    Args:
        path: Absolute or relative path to the file
        content: Content to write
    """
    import asyncio

    p = _safe_path(path)
    loop = asyncio.get_event_loop()
    action = "overwrite" if p.exists() else "create"
    answer = await loop.run_in_executor(
        None,
        lambda: input(f"\n⚠️  Hughie quer {action} o arquivo:\n  {p}\nConfirmar? [s/N]: ").strip().lower(),
    )
    if answer not in ("s", "sim", "y", "yes"):
        return "Write cancelled by user."

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"File written: {p} ({len(content)} chars)"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def list_dir(path: str = ".", show_hidden: bool = False) -> str:
    """List contents of a directory.

    Args:
        path: Directory path (default: current directory)
        show_hidden: Include hidden files/dirs (default: False)
    """
    p = _safe_path(path)
    if not p.exists():
        return f"Error: path not found: {p}"
    if not p.is_dir():
        return f"Error: not a directory: {p}"

    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        lines = []
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            kind = "/" if entry.is_dir() else ""
            try:
                size = "" if entry.is_dir() else f"  {entry.stat().st_size:,} bytes"
            except Exception:
                size = ""
            lines.append(f"{'[dir] ' if entry.is_dir() else '      '}{entry.name}{kind}{size}")

        if not lines:
            return f"Directory is empty: {p}"
        return f"{p}:\n" + "\n".join(lines[:MAX_RESULTS])
    except Exception as e:
        return f"Error listing directory: {e}"


@tool
def find_files(pattern: str, directory: str = ".", max_results: int = 30) -> str:
    """Find files matching a glob pattern within a directory.

    Args:
        pattern: Glob pattern (e.g. '*.py', '**/*.md', 'config.*')
        directory: Directory to search in (default: current directory)
        max_results: Maximum number of results to return
    """
    p = _safe_path(directory)
    if not p.exists() or not p.is_dir():
        return f"Error: directory not found: {p}"

    try:
        matches = list(p.glob(pattern))[:max_results]
        if not matches:
            return f"No files found matching '{pattern}' in {p}"
        lines = [str(m.relative_to(p)) for m in sorted(matches)]
        result = "\n".join(lines)
        if len(matches) == max_results:
            result += f"\n... (showing first {max_results} results)"
        return result
    except Exception as e:
        return f"Error searching files: {e}"


FILESYSTEM_TOOLS = [read_file, write_file, list_dir, find_files]
