from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import ToolCall, ToolCallChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from codex_bridge_sdk import CodexBridgeClient
from hughie.config import get_settings


def _to_sdk_messages(messages: list[BaseMessage]) -> list[dict]:
    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": str(msg.content)})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    result.append({
                        "role": "tool_call",
                        "call_id": tc["id"],
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"]),
                        "content": "",
                    })
            else:
                result.append({"role": "assistant", "content": str(msg.content)})
        elif isinstance(msg, ToolMessage):
            result.append({
                "role": "tool_result",
                "call_id": msg.tool_call_id,
                "content": str(msg.content),
            })
    return result


def _to_tool_definitions(tools: list[Any]) -> list[dict]:
    definitions = []
    for tool in tools:
        if hasattr(tool, "name") and hasattr(tool, "description"):
            schema = tool.args_schema.schema() if hasattr(tool, "args_schema") and tool.args_schema else {}
            definitions.append({
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            })
    return definitions


class CodexChatModel(BaseChatModel):
    model: str = ""
    reasoning_effort: str = "medium"
    timeout: float = 120.0
    _tools: list[Any] = []
    _tool_definitions: list[dict] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        settings = get_settings()
        if not self.model:
            object.__setattr__(self, "model", settings.bridge_model)
        object.__setattr__(self, "timeout", settings.bridge_timeout)
        object.__setattr__(self, "_tools", [])
        object.__setattr__(self, "_tool_definitions", [])

    def _get_client(self) -> CodexBridgeClient:
        settings = get_settings()
        return CodexBridgeClient(base_url=settings.bridge_url, timeout=self.timeout)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "CodexChatModel":
        new = self.__class__(model=self.model, reasoning_effort=self.reasoning_effort)
        object.__setattr__(new, "_tools", list(tools))
        object.__setattr__(new, "_tool_definitions", _to_tool_definitions(tools))
        return new

    def _build_request(self, messages: list[BaseMessage]) -> dict:
        req: dict[str, Any] = {
            "model": self.model,
            "reasoningEffort": self.reasoning_effort,
            "messages": _to_sdk_messages(messages),
        }
        if self._tool_definitions:
            req["tools"] = self._tool_definitions
        return req

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = self._get_client()
        request = self._build_request(messages)
        response = client.chat(request)
        ai_msg = AIMessage(content=response.get("outputText", ""))
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        client = self._get_client()
        request = self._build_request(messages)

        # Track in-flight tool calls: call_id -> {name, args_buf}
        active_tool_calls: dict[str, dict] = {}
        tool_call_index: dict[str, int] = {}
        next_index = 0

        for event in client.iter_stream_chat(request):
            kind = event.get("kind")

            if kind == "delta":
                delta = event.get("delta", "")
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=delta))
                if run_manager:
                    run_manager.on_llm_new_token(delta, chunk=chunk)
                yield chunk

            elif kind == "tool_call_start":
                call_id = event.get("callId", "")
                name = event.get("name", "")
                active_tool_calls[call_id] = {"name": name, "args_buf": ""}
                tool_call_index[call_id] = next_index
                next_index += 1
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            ToolCallChunk(
                                id=call_id,
                                name=name,
                                args="",
                                index=tool_call_index[call_id],
                            )
                        ],
                    )
                )
                yield chunk

            elif kind == "tool_call_delta":
                call_id = event.get("callId", "")
                delta = event.get("delta", "")
                if call_id in active_tool_calls:
                    active_tool_calls[call_id]["args_buf"] += delta
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            ToolCallChunk(
                                id=None,
                                name=None,
                                args=delta,
                                index=tool_call_index.get(call_id, 0),
                            )
                        ],
                    )
                )
                yield chunk

            elif kind == "tool_call_done":
                call_id = event.get("callId", "")
                if call_id in active_tool_calls:
                    tc = active_tool_calls.pop(call_id)
                    try:
                        args = json.loads(tc["args_buf"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    chunk = ChatGenerationChunk(
                        message=AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                ToolCallChunk(
                                    id=call_id,
                                    name=tc["name"],
                                    args=json.dumps(args),
                                    index=tool_call_index.get(call_id, 0),
                                )
                            ],
                        )
                    )
                    yield chunk

    @property
    def _llm_type(self) -> str:
        return "codex-bridge"
