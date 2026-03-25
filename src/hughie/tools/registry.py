"""
Central tool registry.

Collects all tools (brain, shell, filesystem, web, MCP) into a
single list used by Hughie and future agents.

Usage:
    tools = await load_all_tools()
    graph = build_graph(tools)
"""

import logging

from hughie.tools.brain_tools import BRAIN_TOOLS
from hughie.tools.filesystem_tools import FILESYSTEM_TOOLS
from hughie.tools.mcp_loader import load_mcp_tools
from hughie.tools.shell_tool import SHELL_TOOLS
from hughie.tools.web_search_tool import WEB_TOOLS

logger = logging.getLogger(__name__)


async def load_all_tools() -> list:
    """Load all tools including MCP servers."""
    mcp_tools = await load_mcp_tools()

    tools = BRAIN_TOOLS + SHELL_TOOLS + FILESYSTEM_TOOLS + WEB_TOOLS + mcp_tools

    logger.info(
        "Tools loaded: brain=%d shell=%d fs=%d web=%d mcp=%d  total=%d",
        len(BRAIN_TOOLS),
        len(SHELL_TOOLS),
        len(FILESYSTEM_TOOLS),
        len(WEB_TOOLS),
        len(mcp_tools),
        len(tools),
    )
    return tools
