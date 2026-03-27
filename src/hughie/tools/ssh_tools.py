"""
SSH tools — execute commands and read/write files on remote hosts.

Hosts are resolved via ~/.ssh/config, so any alias defined there works.
Read-only commands run without confirmation; write/destructive ones ask first.
"""

import asyncio
import hashlib
import re
import shlex
from langchain_core.tools import tool
from hughie.approvals import confirm_or_raise

_READ_ONLY = frozenset([
    "ls", "ll", "la", "cat", "head", "tail", "less", "more",
    "grep", "rg", "find", "locate", "fd",
    "pwd", "echo", "whoami", "id", "uname", "hostname",
    "which", "whereis",
    "ps", "df", "du", "free", "uptime", "w",
    "git log", "git status", "git diff", "git show",
    "git branch", "git remote", "git tag", "git stash list",
    "wc", "sort", "uniq", "awk", "sed", "cut", "tr",
    "python --version", "python3 --version",
    "pip list", "pip show", "pip freeze",
    "docker ps", "docker images", "docker logs", "docker inspect",
    "systemctl status", "journalctl",
    "env", "printenv",
    "date", "tree", "jq", "yq",
    "curl", "wget",
])

SSH_TIMEOUT = 30
OUTPUT_LIMIT = 8_000
_WRITE_PATTERNS = (
    r">",
    r"\|\s*tee\b",
    r"\b(rm|mv|cp|touch|mkdir|rmdir|chmod|chown|ln|truncate)\b",
    r"\bsed\s+-i\b",
)


def _ssh_base(host: str) -> list[str]:
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        host,
    ]


def _is_read_only(command: str) -> bool:
    cmd = command.strip()
    if any(re.search(pattern, cmd) for pattern in _WRITE_PATTERNS):
        return False
    first = cmd.split()[0] if cmd.split() else ""
    if first in _READ_ONLY:
        return True
    for safe in _READ_ONLY:
        if " " in safe and cmd.startswith(safe):
            return True
    return False


async def _run(host: str, command: str, stdin: bytes | None = None) -> str:
    cmd = _ssh_base(host) + [command]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(input=stdin), timeout=SSH_TIMEOUT)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > OUTPUT_LIMIT:
            output = output[:OUTPUT_LIMIT] + f"\n... [truncado — {len(output)} chars total]"
        if proc.returncode != 0 and not output.strip():
            return f"[exit {proc.returncode}] (sem output)"
        return output or f"[exit {proc.returncode}]"
    except asyncio.TimeoutError:
        return f"[timeout após {SSH_TIMEOUT}s]"
    except FileNotFoundError:
        return "[erro: comando 'ssh' não encontrado no PATH]"
    except Exception as exc:
        return f"[ssh error: {exc}]"


@tool
async def ssh_exec(host: str, command: str, working_dir: str = "") -> str:
    """Execute a shell command on a remote host via SSH.

    Read-only commands (ls, cat, git log, docker ps, etc.) run automatically.
    Write or destructive commands ask for confirmation first.

    Uses ~/.ssh/config, so any configured alias works (e.g. 'home-server').

    Args:
        host: SSH host alias or user@hostname (e.g. 'home-server', 'elian@192.168.1.10')
        command: Shell command to execute
        working_dir: Optional working directory on the remote host
    """
    full_command = f"cd {shlex.quote(working_dir)} && {command}" if working_dir else command

    if not _is_read_only(command):
        confirmed = await confirm_or_raise(
            action_key=f"ssh_exec:{host}:{working_dir}:{command}",
            prompt=f"⚠️  Hughie quer executar em [{host}]:\n  {full_command}",
            approve_label="Autorizar comando remoto",
            reject_label="Negar comando remoto",
        )
        if not confirmed:
            return "Comando cancelado pelo usuário."

    return await _run(host, full_command)


@tool
async def ssh_read_file(host: str, path: str) -> str:
    """Read the contents of a file on a remote host via SSH.

    Args:
        host: SSH host alias or user@hostname
        path: Absolute path to the file on the remote host
    """
    return await _run(host, f"cat {shlex.quote(path)}")


@tool
async def ssh_write_file(host: str, path: str, content: str) -> str:
    """Write content to a file on a remote host via SSH.

    Always asks for confirmation before writing.

    Args:
        host: SSH host alias or user@hostname
        path: Absolute path to the file on the remote host
        content: Content to write (overwrites existing file)
    """
    confirmed = await confirm_or_raise(
        action_key=f"ssh_write_file:{host}:{path}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        prompt=f"⚠️  Hughie quer escrever {len(content)} chars em [{host}]:\n  {path}",
        approve_label="Autorizar escrita remota",
        reject_label="Negar escrita remota",
    )
    if not confirmed:
        return "Cancelado pelo usuário."

    # Write via stdin piped into `cat > path` — handles any content safely
    cmd = _ssh_base(host) + [f"cat > {shlex.quote(path)}"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=content.encode("utf-8")),
            timeout=SSH_TIMEOUT,
        )
        if proc.returncode != 0:
            err = stdout.decode("utf-8", errors="replace")
            return f"[erro ao escrever, exit {proc.returncode}]: {err}"
        return f"Arquivo escrito: {path} ({len(content)} chars)"
    except asyncio.TimeoutError:
        return f"[timeout após {SSH_TIMEOUT}s]"
    except Exception as exc:
        return f"[ssh error: {exc}]"


@tool
async def ssh_list_dir(host: str, path: str, hidden: bool = False) -> str:
    """List the contents of a directory on a remote host via SSH.

    Args:
        host: SSH host alias or user@hostname
        path: Absolute path to the directory
        hidden: Include hidden files (default False)
    """
    flag = "-la" if hidden else "-l"
    return await _run(host, f"ls {flag} {shlex.quote(path)}")


SSH_TOOLS = [ssh_exec, ssh_read_file, ssh_write_file, ssh_list_dir]
