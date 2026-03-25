"""Web search via DuckDuckGo (no API key required)."""

from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo.

    Use this to find current information, documentation, news,
    or anything that requires looking up online.

    Args:
        query: Search query
        max_results: Number of results to return (default: 5)
    """
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return "No results found."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   {r.get('href', '')}")
            body = r.get("body", "")
            if body:
                lines.append(f"   {body[:200]}")
            lines.append("")

        return "\n".join(lines).strip()

    except Exception as e:
        return f"Search error: {e}"


WEB_TOOLS = [web_search]
