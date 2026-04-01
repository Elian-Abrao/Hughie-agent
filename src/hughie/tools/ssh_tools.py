"""
SSH tools — execute commands and read/write files on remote hosts.

Hosts are resolved via ~/.ssh/config, so any alias defined there works.
Read-only commands run without confirmation; write/destructive ones ask first.
"""

import asyncio
import re
import shlex
from langchain_core.tools import tool
from hughie.approvals import confirm_or_raise
from hughie.host_agent.client import get_host_agent_client, should_use_host_agent

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


def _extract_scope_dir(command: str, working_dir: str) -> str | None:
    if working_dir:
        return working_dir
    cmd = command.strip()
    if cmd.startswith("cd "):
        remainder = cmd[3:]
        scope = remainder.split("&&", 1)[0].strip()
        parts = shlex.split(scope) if scope else []
        return parts[0] if parts else None
    return None


def _describe_remote_command(host: str, command: str, working_dir: str) -> tuple[str, str, str | None]:
    scope_dir = _extract_scope_dir(command, working_dir)
    cmd = command.strip()
    if any(re.search(pattern, cmd) for pattern in _WRITE_PATTERNS):
        message = f"Hughie quer alterar arquivos em [{host}]"
    elif "python" in cmd or "find " in cmd or "rg " in cmd or "glob" in cmd or "os.walk" in cmd:
        message = f"Hughie quer analisar arquivos em [{host}]"
    else:
        message = f"Hughie quer executar um comando avançado em [{host}]"

    if scope_dir:
        message += f" dentro de:\n{scope_dir}\n\nSe você autorizar, ele pode continuar trabalhando nesse diretório sem pedir confirmação a cada passo."
        return message, "Autorizar neste diretório", f"ssh_exec_prefix|{host}|{scope_dir}"

    return message, "Autorizar comando remoto", None


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
        prompt, approve_label, scope_key = _describe_remote_command(host, command, working_dir)
        confirmed = await confirm_or_raise(
            action_key=f"ssh_exec:{host}:{working_dir}:{command}",
            prompt=prompt,
            approve_label=approve_label,
            reject_label="Negar comando remoto",
            scope_key=scope_key,
        )
        if not confirmed:
            return "Comando cancelado pelo usuário."

    if should_use_host_agent(host):
        client = get_host_agent_client()
        if client and await asyncio.to_thread(client.health):
            return await asyncio.to_thread(client.exec, command, working_dir)
    return await _run(host, full_command)


@tool
async def ssh_read_file(host: str, path: str) -> str:
    """Read the contents of a file on a remote host via SSH.

    Args:
        host: SSH host alias or user@hostname
        path: Absolute path to the file on the remote host
    """
    if should_use_host_agent(host):
        client = get_host_agent_client()
        if client and await asyncio.to_thread(client.health):
            return await asyncio.to_thread(client.read_file, path)
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
        action_key=f"ssh_write_file:{host}:{path}",
        prompt=(
            f"Hughie quer escrever um arquivo em [{host}] dentro de:\n{path.rsplit('/', 1)[0] if '/' in path else path}\n\n"
            "Se você autorizar, ele pode continuar gravando nesse diretório sem pedir de novo agora."
        ),
        approve_label="Autorizar neste diretório",
        reject_label="Negar escrita remota",
        scope_key=f"ssh_write_prefix|{host}|{path.rsplit('/', 1)[0] if '/' in path else path}",
    )
    if not confirmed:
        return "Cancelado pelo usuário."

    if should_use_host_agent(host):
        client = get_host_agent_client()
        if client and await asyncio.to_thread(client.health):
            return await asyncio.to_thread(client.write_file, path, content)

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
    if should_use_host_agent(host):
        client = get_host_agent_client()
        if client and await asyncio.to_thread(client.health):
            return await asyncio.to_thread(client.list_dir, path, hidden)
    flag = "-la" if hidden else "-l"
    return await _run(host, f"ls {flag} {shlex.quote(path)}")


SSH_TOOLS = [ssh_exec, ssh_read_file, ssh_write_file, ssh_list_dir]
