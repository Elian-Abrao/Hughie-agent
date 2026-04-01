import asyncio
import logging
import re
import shlex
from pathlib import Path

from hughie.host_agent.client import get_host_agent_client, should_use_host_agent

logger = logging.getLogger(__name__)

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


async def classify_paths_ssh_batch(host: str, paths: list[str]) -> dict[str, str | None]:
    """Check N paths on a remote host in a single SSH connection.

    Returns a dict mapping each path to "file", "directory", or None (not found / error).
    Falls back to empty dict if SSH is unreachable.
    """
    if not paths:
        return {}

    if should_use_host_agent(host):
        client = get_host_agent_client()
        if client and await asyncio.to_thread(client.health):
            try:
                return await asyncio.to_thread(client.classify_paths, paths)
            except Exception as exc:
                logger.warning("Host-agent path check failed for %s: %s", host, exc)

    # Build one bash command that checks every path and prints "path:kind"
    checks = "; ".join(
        'p={}; echo -n "$p:"; [ -f "$p" ] && echo file || {{ [ -d "$p" ] && echo directory || echo none; }}'.format(
            shlex.quote(p)
        )
        for p in paths
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            host,
            f"bash -c {shlex.quote(checks)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
        result: dict[str, str | None] = {}
        for line in stdout.decode(errors="replace").splitlines():
            if ":" not in line:
                continue
            path, _, kind = line.rpartition(":")
            kind = kind.strip()
            result[path] = kind if kind in ("file", "directory") else None
        return result
    except Exception as exc:
        logger.warning("SSH batch path check failed for %s: %s", host, exc)
        return {}
