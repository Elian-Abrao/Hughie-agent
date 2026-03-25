from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from hughie.core.nodes import chat, retrieve_context, save_memory
from hughie.core.state import HughieState
from hughie.tools.brain_tools import BRAIN_TOOLS

_graph = None


def build_graph():
    global _graph
    if _graph is not None:
        return _graph

    builder = StateGraph(HughieState)

    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("chat", chat)
    builder.add_node("tools", ToolNode(BRAIN_TOOLS))
    builder.add_node("save_memory", save_memory)

    builder.add_edge(START, "retrieve_context")
    builder.add_edge("retrieve_context", "chat")

    # ReAct loop: if LLM calls tools, execute them and return to chat
    builder.add_conditional_edges(
        "chat",
        tools_condition,
        {"tools": "tools", END: "save_memory"},
    )
    builder.add_edge("tools", "chat")
    builder.add_edge("save_memory", END)

    _graph = builder.compile()
    return _graph
