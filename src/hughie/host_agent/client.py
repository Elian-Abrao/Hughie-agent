from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from hughie.config import get_settings


@dataclass
class HostAgentClient:
    base_url: str
    token: str = ""
    timeout: float = 10.0

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def health(self) -> bool:
        try:
            payload = self._request("GET", "/health")
            return bool(payload.get("ok"))
        except (OSError, ValueError, error.URLError):
            return False

    def exec(self, command: str, working_dir: str = "") -> str:
        payload = self._request("POST", "/v1/exec", {"command": command, "working_dir": working_dir})
        return str(payload.get("output", ""))

    def read_file(self, path: str) -> str:
        payload = self._request("POST", "/v1/read-file", {"path": path})
        return str(payload.get("content", ""))

    def write_file(self, path: str, content: str) -> str:
        payload = self._request("POST", "/v1/write-file", {"path": path, "content": content})
        return str(payload.get("message", ""))

    def list_dir(self, path: str, hidden: bool = False) -> str:
        payload = self._request("POST", "/v1/list-dir", {"path": path, "hidden": hidden})
        return str(payload.get("output", ""))

    def classify_paths(self, paths: list[str]) -> dict[str, str | None]:
        payload = self._request("POST", "/v1/classify-paths", {"paths": paths})
        result = payload.get("results", {})
        return result if isinstance(result, dict) else {}


_client: HostAgentClient | None = None


def get_host_agent_client() -> HostAgentClient | None:
    global _client
    settings = get_settings()
    if not settings.host_agent_url.strip():
        return None
    if _client is None or _client.base_url != settings.host_agent_url or _client.token != settings.host_agent_token:
        _client = HostAgentClient(
            base_url=settings.host_agent_url.strip(),
            token=settings.host_agent_token,
            timeout=settings.host_agent_timeout,
        )
    return _client


def should_use_host_agent(host: str) -> bool:
    settings = get_settings()
    if not settings.host_agent_url.strip():
        return False
    return host.strip() == settings.local_machine_host
