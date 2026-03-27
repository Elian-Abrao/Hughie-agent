"""Shell execution tool with read/write detection."""

import re
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


def _describe_sensitive_command(command: str, working_dir: str) -> tuple[str, str, str | None]:
    scope_dir = _extract_scope_dir(command, working_dir)
    cmd = command.strip()
    if any(re.search(pattern, cmd) for pattern in _WRITE_PATTERNS):
        message = "Hughie quer alterar arquivos locais"
    elif "python" in cmd or "find " in cmd or "rg " in cmd or "glob" in cmd or "os.walk" in cmd:
        message = "Hughie quer analisar arquivos locais"
    else:
        message = "Hughie quer executar um comando local avançado"

    if scope_dir:
        message += f" em:\n{scope_dir}\n\nSe você autorizar, ele poderá continuar neste diretório sem pedir confirmação a cada passo."
        return message, "Autorizar neste diretório", f"shell_exec_prefix|{scope_dir}"

    return message, "Autorizar comando", None


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
        prompt, approve_label, scope_key = _describe_sensitive_command(command, working_dir)
        confirmed = await confirm_or_raise(
            action_key=f"shell_exec:{working_dir}:{command}",
            prompt=prompt,
            approve_label=approve_label,
            reject_label="Negar comando",
            scope_key=scope_key,
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
