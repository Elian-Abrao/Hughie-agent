from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import urlopen

from hughie.config import get_settings

_LOG_PATH = Path.home() / ".hughie" / "llm-broker.log"


def _health_url() -> str:
    settings = get_settings()
    base = settings.bridge_url.rstrip("/") + "/"
    return urljoin(base, "v1/health")


def _broker_command() -> list[str]:
    exe = shutil.which("llm-broker")
    if exe:
        return [exe, "serve"]
    return [sys.executable, "-m", "llm_broker", "serve"]


def _is_broker_healthy() -> bool:
    try:
        with urlopen(_health_url(), timeout=1.5) as response:
            return 200 <= response.status < 300
    except (URLError, OSError):
        return False


def _start_broker_process() -> subprocess.Popen:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_PATH.open("ab")
    env = os.environ.copy()
    return subprocess.Popen(
        _broker_command(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )


async def ensure_broker_ready(timeout: float = 20.0) -> bool:
    """Ensure the local llm-broker is serving requests."""
    if _is_broker_healthy():
        return False

    try:
        process = await asyncio.to_thread(_start_broker_process)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Não consegui iniciar o llm-broker automaticamente. "
            "Instale o broker ou verifique se o módulo 'llm_broker' está disponível."
        ) from exc

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_broker_healthy():
            return True
        if process.poll() is not None:
            raise RuntimeError(
                "O llm-broker foi iniciado automaticamente, mas encerrou logo em seguida. "
                f"Veja o log em {_LOG_PATH}."
            )
        await asyncio.sleep(0.5)

    raise RuntimeError(
        "O llm-broker não ficou saudável a tempo. "
        f"Veja o log em {_LOG_PATH}."
    )
