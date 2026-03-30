from typing import Annotated
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class HughieState(TypedDict):
    messages: Annotated[list, add_messages]  # turno atual + tool calls
    history: list                             # histórico anterior carregado do DB
    session_id: str
    brain_context: str
    user_message_presaved: NotRequired[bool]  # True quando endpoint já salvou a msg do user
