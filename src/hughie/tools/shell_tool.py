"""Shell execution tool with read/write detection."""

import shlex
import subprocess
from langchain_core.tools import tool
from hughie.approvals import confirm_or_raise

# Commands considered safe to run without confirmation
_READ_ONLY = frozenset([
    "ls", "ll", "la", "cat", "head", "tail", "less", "more",
    "grep", "rg", "find", "locate", "fd",
    "pwd", "echo", "printf", "whoami", "id", "uname", "hostname",
    "which", "type", "whereis",
    "ps", "df", "du", "free", "uptime", "w", "top", "htop",
    "git log", "git status", "git diff", "git show",
    "git branch", "git remote", "git tag", "git stash list",
    "git log", "git shortlog",
    "wc", "sort", "uniq", "awk", "sed", "cut", "tr",
    "python --version", "python3 --version",
    "pip list", "pip show", "pip freeze",
    "docker ps", "docker images", "docker logs", "docker inspect",
    "systemctl status", "journalctl",
    "env", "printenv",
    "date", "cal",
    "curl", "wget",
    "jq", "yq",
    "tree",
])

MAX_OUTPUT = 8_000  # chars returned to LLM


def _is_read_only(command: str) -> bool:
    cmd = command.strip()
    first = cmd.split()[0] if cmd.split() else ""
    if first in _READ_ONLY:
        return True
    for safe in _READ_ONLY:
        if " " in safe and cmd.startswith(safe):
            return True
    return False


@tool
async def shell_exec(command: str, working_dir: str = "") -> str:
    """Execute a shell command on the local machine.

    Read-only commands run automatically. Write/destructive commands
    ask for user confirmation first.

    Args:
        command: The bash command to execute
        working_dir: Optional working directory (absolute path)
    """
    if not _is_read_only(command):
        display_command = f"cd {shlex.quote(working_dir)} && {command}" if working_dir else command
        confirmed = await confirm_or_raise(
            action_key=f"shell_exec:{working_dir}:{command}",
            prompt=f"⚠️  Hughie quer executar:\n  {display_command}",
            approve_label="Autorizar comando",
            reject_label="Negar comando",
        )
        if not confirmed:
            return "Command cancelled by user."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir or None,
            timeout=30,
        )
        output = result.stdout + result.stderr
        if not output.strip():
            return f"Command completed with exit code {result.returncode} (no output)."
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + f"\n... [truncated, {len(output)} chars total]"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds."
    except Exception as e:
        return f"Error: {e}"


SHELL_TOOLS = [shell_exec]
