from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from hughie.config import get_settings

MAX_OUTPUT = 20_000
MAX_READ = 100_000

app = FastAPI(title="Hughie Host Agent", version="0.1.0")


class ExecRequest(BaseModel):
    command: str
    working_dir: str = ""


class ReadFileRequest(BaseModel):
    path: str


class WriteFileRequest(BaseModel):
    path: str
    content: str


class ListDirRequest(BaseModel):
    path: str
    hidden: bool = False


class ClassifyPathsRequest(BaseModel):
    paths: list[str]


def _check_auth(authorization: str | None) -> None:
    token = get_settings().host_agent_token.strip()
    if not token:
        return
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


@app.get("/health")
async def health(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return {"ok": True, "service": "hughie-host-agent"}


@app.post("/v1/exec")
async def exec_command(req: ExecRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    try:
        result = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=req.working_dir or None,
            timeout=30,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + f"\n... [truncated, {len(output)} chars total]"
        return {"output": output or f"Command completed with exit code {result.returncode}."}
    except subprocess.TimeoutExpired:
        return {"output": "Error: command timed out after 30 seconds."}
    except Exception as exc:
        return {"output": f"Error: {exc}"}


@app.post("/v1/read-file")
async def read_file(req: ReadFileRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    path = _safe_path(req.path)
    if not path.exists():
        return {"content": f"Error: file not found: {path}"}
    if not path.is_file():
        return {"content": f"Error: path is not a file: {path}"}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_READ:
            content = content[:MAX_READ] + f"\n... [truncated, {len(content)} chars total]"
        return {"content": content}
    except Exception as exc:
        return {"content": f"Error reading file: {exc}"}


@app.post("/v1/write-file")
async def write_file(req: WriteFileRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    path = _safe_path(req.path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.content, encoding="utf-8")
        return {"message": f"File written: {path} ({len(req.content)} chars)"}
    except Exception as exc:
        return {"message": f"Error writing file: {exc}"}


@app.post("/v1/list-dir")
async def list_dir(req: ListDirRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    path = _safe_path(req.path)
    if not path.exists():
        return {"output": f"Error: path not found: {path}"}
    if not path.is_dir():
        return {"output": f"Error: not a directory: {path}"}
    entries = sorted(path.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
    lines: list[str] = []
    for entry in entries:
        if not req.hidden and entry.name.startswith("."):
            continue
        suffix = "/" if entry.is_dir() else ""
        size = ""
        if not entry.is_dir():
            try:
                size = f"  {entry.stat().st_size:,} bytes"
            except OSError:
                size = ""
        lines.append(f"{'[dir] ' if entry.is_dir() else '      '}{entry.name}{suffix}{size}")
    return {"output": f"{path}:\n" + "\n".join(lines[:100]) if lines else f"Directory is empty: {path}"}


@app.post("/v1/classify-paths")
async def classify_paths(req: ClassifyPathsRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    results: dict[str, str | None] = {}
    for raw_path in req.paths:
        try:
            path = _safe_path(raw_path)
            if path.exists() and path.is_file():
                results[raw_path] = "file"
            elif path.exists() and path.is_dir():
                results[raw_path] = "directory"
            else:
                results[raw_path] = None
        except Exception:
            results[raw_path] = None
    return {"results": results}
