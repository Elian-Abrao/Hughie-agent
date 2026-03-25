from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from hughie.core.nodes import chat, retrieve_context, save_memory
from hughie.core.state import HughieState


def build_graph(tools: list):
    builder = StateGraph(HughieState)

    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("chat", chat)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("save_memory", save_memory)

    builder.add_edge(START, "retrieve_context")
    builder.add_edge("retrieve_context", "chat")

    builder.add_conditional_edges(
        "chat",
        tools_condition,
        {"tools": "tools", END: "save_memory"},
    )
    builder.add_edge("tools", "chat")
    builder.add_edge("save_memory", END)

    return builder.compile()
