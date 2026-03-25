"""
MCP (Model Context Protocol) loader.

Reads mcp_servers.json from the project root and connects to
configured MCP servers, returning LangChain-compatible tools.

Example mcp_servers.json:
{
  "filesystem": {
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/elian"]
  },
  "github": {
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}
  }
}
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MCP_CONFIG_FILE = Path(__file__).parents[3] / "mcp_servers.json"
_mcp_client = None


def _load_config() -> dict:
    if not _MCP_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(_MCP_CONFIG_FILE.read_text())
    except Exception as e:
        logger.warning("Failed to load mcp_servers.json: %s", e)
        return {}


async def load_mcp_tools() -> list:
    """Connect to configured MCP servers and return their tools."""
    global _mcp_client

    config = _load_config()
    if not config:
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        _mcp_client = MultiServerMCPClient(config)
        await _mcp_client.__aenter__()
        tools = _mcp_client.get_tools()
        logger.info("Loaded %d tools from %d MCP server(s)", len(tools), len(config))
        return tools
    except Exception as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return []


async def close_mcp_client() -> None:
    global _mcp_client
    if _mcp_client is not None:
        try:
            await _mcp_client.__aexit__(None, None, None)
        except Exception:
            pass
        _mcp_client = None
