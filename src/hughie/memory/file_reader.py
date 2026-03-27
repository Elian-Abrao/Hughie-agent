import re
from pathlib import Path

# Matches absolute paths to files or directories.
_PATH_RE = re.compile(r"(?<!['\"\w])(/(?:[a-zA-Z0-9_\-\.]+/?)+)")

MAX_FILE_SIZE = 100_000   # 100 KB
MAX_CONTENT_PER_FILE = 4_000  # chars sent to LLM per file


def extract_paths(text: str) -> list[str]:
    results: list[str] = []
    for raw in _PATH_RE.findall(text):
        cleaned = raw.rstrip(".,:;)]}\"'")
        if cleaned not in results:
            results.append(cleaned)
    return results


def classify_path(path: str) -> str | None:
    try:
        p = Path(path).expanduser().resolve()
        if p.exists() and p.is_file():
            return "file"
        if p.exists() and p.is_dir():
            return "directory"
    except Exception:
        pass
    return None


def read_file(path: str) -> str | None:
    try:
        p = Path(path).expanduser().resolve()
        if p.exists() and p.is_file() and p.stat().st_size <= MAX_FILE_SIZE:
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return None


def collect_file_contents(conversation_text: str) -> dict[str, str]:
    """Extract all readable file paths mentioned in a conversation."""
    result = {}
    for path in extract_paths(conversation_text):
        if classify_path(path) != "file":
            continue
        content = read_file(path)
        if content:
            result[path] = content[:MAX_CONTENT_PER_FILE]
    return result
