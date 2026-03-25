from typing import Annotated
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class HughieState(TypedDict):
    messages: Annotated[list, add_messages]  # turno atual + tool calls
    history: list                             # histórico anterior carregado do DB
    session_id: str
    brain_context: str
