import re
from pathlib import Path

# Matches absolute paths with an extension: /foo/bar/file.ext
_PATH_RE = re.compile(r"(?<!['\"\w])(/(?:[a-zA-Z0-9_\-\.]+/)*[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)")

MAX_FILE_SIZE = 100_000   # 100 KB
MAX_CONTENT_PER_FILE = 4_000  # chars sent to LLM per file


def extract_paths(text: str) -> list[str]:
    return list(dict.fromkeys(_PATH_RE.findall(text)))  # deduplicated, order preserved


def read_file(path: str) -> str | None:
    try:
        p = Path(path)
        if p.exists() and p.is_file() and p.stat().st_size <= MAX_FILE_SIZE:
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return None


def collect_file_contents(conversation_text: str) -> dict[str, str]:
    """Extract all readable file paths mentioned in a conversation."""
    result = {}
    for path in extract_paths(conversation_text):
        content = read_file(path)
        if content:
            result[path] = content[:MAX_CONTENT_PER_FILE]
    return result
