import asyncio

from hughie.memory import file_reader
from hughie.tools import ssh_tools


class FakeHostAgentClient:
    def health(self) -> bool:
        return True

    def exec(self, command: str, working_dir: str = "") -> str:
        return f"host-agent exec: {working_dir}|{command}"

    def read_file(self, path: str) -> str:
        return f"host-agent read: {path}"

    def write_file(self, path: str, content: str) -> str:
        return f"host-agent write: {path} ({len(content)})"

    def list_dir(self, path: str, hidden: bool = False) -> str:
        return f"host-agent list: {path} hidden={hidden}"

    def classify_paths(self, paths: list[str]) -> dict[str, str | None]:
        return {path: "file" for path in paths}


def test_ssh_exec_prefers_host_agent(monkeypatch):
    monkeypatch.setattr(ssh_tools, "should_use_host_agent", lambda host: True)
    monkeypatch.setattr(ssh_tools, "get_host_agent_client", lambda: FakeHostAgentClient())

    async def fail_run(*args, **kwargs):
        raise AssertionError("SSH fallback should not be used when host-agent is healthy")

    monkeypatch.setattr(ssh_tools, "_run", fail_run)

    result = asyncio.run(ssh_tools.ssh_exec.coroutine("tree-dev", "pwd", "/tmp"))

    assert result == "host-agent exec: /tmp|pwd"


def test_classify_paths_batch_prefers_host_agent(monkeypatch):
    monkeypatch.setattr(file_reader, "should_use_host_agent", lambda host: True)
    monkeypatch.setattr(file_reader, "get_host_agent_client", lambda: FakeHostAgentClient())

    result = asyncio.run(file_reader.classify_paths_ssh_batch("tree-dev", ["/tmp/a", "/tmp/b"]))

    assert result == {"/tmp/a": "file", "/tmp/b": "file"}
