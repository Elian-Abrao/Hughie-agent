from __future__ import annotations

import json
from typing import Any

from codex_bridge_sdk import BridgeClientError, BridgeHttpError, CodexBridgeClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="codex-bridge FastAPI example", version="0.1.0")
bridge = CodexBridgeClient()


class ChatMessageModel(BaseModel):
    role: str
    content: str


class ChatRequestModel(BaseModel):
    model: str | None = None
    reasoning_effort: str | None = Field(default=None, alias="reasoningEffort")
    messages: list[ChatMessageModel]
    temperature: float | None = None
    metadata: dict[str, str] | None = None

    def to_bridge_payload(self) -> dict[str, Any]:
        payload = {
            "messages": [message.model_dump() for message in self.messages],
        }

        if self.model:
            payload["model"] = self.model
        if self.reasoning_effort:
            payload["reasoningEffort"] = self.reasoning_effort
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.metadata:
            payload["metadata"] = self.metadata

        return payload


class CompleteLoginRequestModel(BaseModel):
    redirect_url: str = Field(alias="redirectUrl")


def _raise_bridge_error(exc: Exception) -> None:
    if isinstance(exc, BridgeHttpError):
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "statusCode": exc.status_code,
                "bridgeBody": exc.body,
            },
        ) from exc

    if isinstance(exc, BridgeClientError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    raise exc


def _format_sse_event(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=True)}\n\n"


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/bridge/health")
def bridge_health() -> dict[str, Any]:
    try:
        return bridge.health()
    except Exception as exc:
        _raise_bridge_error(exc)


@app.get("/bridge/auth/state")
def bridge_auth_state() -> dict[str, Any]:
    try:
        return bridge.get_auth_state()
    except Exception as exc:
        _raise_bridge_error(exc)


@app.post("/bridge/auth/login")
def bridge_auth_login() -> dict[str, Any]:
    try:
        return bridge.start_login()
    except Exception as exc:
        _raise_bridge_error(exc)


@app.post("/bridge/auth/complete")
def bridge_auth_complete(request_model: CompleteLoginRequestModel) -> dict[str, Any]:
    try:
        return bridge.complete_login(request_model.redirect_url)
    except Exception as exc:
        _raise_bridge_error(exc)


@app.get("/bridge/providers/codex/options")
def bridge_codex_options() -> dict[str, Any]:
    try:
        return bridge.get_codex_capabilities()
    except Exception as exc:
        _raise_bridge_error(exc)


@app.post("/bridge/chat")
def bridge_chat(request_model: ChatRequestModel) -> dict[str, Any]:
    try:
        return bridge.chat(request_model.to_bridge_payload())
    except Exception as exc:
        _raise_bridge_error(exc)


@app.post("/bridge/chat/stream")
def bridge_chat_stream(request_model: ChatRequestModel) -> StreamingResponse:
    payload = request_model.to_bridge_payload()

    def event_stream() -> Any:
        try:
            for event in bridge.iter_stream_chat(payload):
                yield _format_sse_event(event)
        except Exception as exc:
            if isinstance(exc, BridgeHttpError):
                yield _format_sse_event(
                    {
                        "requestId": "proxy",
                        "provider": "codex",
                        "kind": "error",
                        "message": str(exc),
                        "statusCode": exc.status_code,
                    }
                )
                return

            if isinstance(exc, BridgeClientError):
                yield _format_sse_event(
                    {
                        "requestId": "proxy",
                        "provider": "codex",
                        "kind": "error",
                        "message": str(exc),
                    }
                )
                return

            raise

    return StreamingResponse(event_stream(), media_type="text/event-stream")
