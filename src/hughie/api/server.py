"""
Hughie HTTP API — FastAPI server with SSE streaming.

Endpoints:
  GET  /health
  POST /v1/chat          — non-streaming, returns full response
  POST /v1/chat/stream   — SSE streaming, yields text chunks + tool events
  GET  /v1/brain/notes   — list brain notes
  GET  /v1/brain/search  — semantic search
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from hughie.approvals import ApprovalRequired, approval_context, register_decision
from hughie.core.graph import build_graph
from hughie.core.nodes import init_llm
from hughie.llm.broker_runtime import ensure_broker_ready
from hughie.memory import brain_store, conversation_store, link_store
from hughie.memory.database import close_pool, run_migrations
from hughie.tools.mcp_loader import close_mcp_client
from hughie.tools.registry import load_all_tools

logger = logging.getLogger(__name__)

_graph = None
_pending_chats: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    logger.info("Inicializando Hughie API...")
    await ensure_broker_ready()
    await run_migrations()
    tools = await load_all_tools()
    init_llm(tools)
    _graph = build_graph(tools)
    logger.info("Hughie API pronta.")
    yield
    await close_mcp_client()
    await close_pool()
    logger.info("Hughie API encerrada.")


app = FastAPI(title="Hughie API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ChatDecisionRequest(BaseModel):
    session_id: str
    decision: str


class NoteUpdateRequest(BaseModel):
    title: str
    content: str
    type: str
    importance: float = 1.0
    status: str = "active"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "service": "hughie"}


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    from hughie.config import get_settings
    settings = get_settings()
    state = {
        "messages": [HumanMessage(content=req.message)],
        "history": [],
        "session_id": session_id,
        "brain_context": "",
    }
    try:
        with approval_context(session_id=session_id, mode="web"):
            result = await _graph.ainvoke(state, {"recursion_limit": settings.recursion_limit})
    except ApprovalRequired as approval:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "approval_required",
                "session_id": session_id,
                "message": approval.message,
                "approve_label": approval.approve_label,
                "reject_label": approval.reject_label,
            },
        )
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            return {"reply": msg.content, "session_id": session_id}
    return {"reply": "", "session_id": session_id}


def _build_chat_state(message: str, session_id: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=message)],
        "history": [],
        "session_id": session_id,
        "brain_context": "",
    }


def _build_approval_message(original_message: str, tools_used: list[str]) -> str:
    tool_summary = ", ".join(tools_used[-4:]) if tools_used else "fazer mais navegação e leitura"
    return (
        "Estou perto do limite desta rodada e ainda quero continuar a investigação. "
        f"Próximo passo provável: {tool_summary}. "
        "Quer que eu continue navegando ou prefere que eu responda agora com o que já consegui levantar?"
    )


def _approval_event(
    *,
    session_id: str,
    message: str,
    approve_label: str,
    reject_label: str,
    approve_decision: str,
    reject_decision: str,
):
    return {
        "event": "approval",
        "data": json.dumps(
            {
                "session_id": session_id,
                "message": message,
                "approve_label": approve_label,
                "reject_label": reject_label,
                "approve_decision": approve_decision,
                "reject_decision": reject_decision,
            }
        ),
    }


async def _stream_chat_run(
    *,
    state: dict[str, Any],
    session_id: str,
    recursion_limit: int,
    allow_pause: bool,
):
    prev_node = ""
    step_count = 0
    tools_used: list[str] = []
    approval_threshold = max(1, recursion_limit - 2)
    original_message = ""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            original_message = str(msg.content)
            break

    try:
        with approval_context(session_id=session_id, mode="web"):
            async for chunk, metadata in _graph.astream(
                state,
                stream_mode="messages",
                config={"recursion_limit": recursion_limit},
            ):
                node = metadata.get("langgraph_node", "")
                if node and node != prev_node:
                    prev_node = node
                    step_count += 1

                    if allow_pause and node == "tools" and step_count >= approval_threshold:
                        _pending_chats[session_id] = {
                            "type": "run_budget",
                            "message": original_message,
                            "tools": list(tools_used),
                            "recursion_limit": recursion_limit,
                        }
                        yield _approval_event(
                            session_id=session_id,
                            message=_build_approval_message(original_message, tools_used),
                            approve_label="Continuar",
                            reject_label="Responder agora",
                            approve_decision="continue",
                            reject_decision="respond_now",
                        )
                        return

                if (
                    isinstance(chunk, AIMessageChunk)
                    and node == "chat"
                    and chunk.content
                    and not getattr(chunk, "tool_call_chunks", None)
                ):
                    yield {"event": "text", "data": json.dumps({"text": chunk.content})}

                elif node == "tools":
                    tool_name = getattr(chunk, "name", None)
                    if tool_name:
                        tools_used.append(tool_name)
                        yield {"event": "tool", "data": json.dumps({"tool": tool_name})}
    except ApprovalRequired as approval:
        _pending_chats[session_id] = {
            "type": "tool_confirmation",
            "message": original_message,
            "action_key": approval.action_key,
            "approve_label": approval.approve_label,
            "reject_label": approval.reject_label,
            "approval_message": approval.message,
        }
        yield _approval_event(
            session_id=session_id,
            message=approval.message,
            approve_label=approval.approve_label,
            reject_label=approval.reject_label,
            approve_decision="approve",
            reject_decision="deny",
        )
        return


@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    from hughie.config import get_settings
    settings = get_settings()

    async def generate():
        # Confirm session_id first so client can track it
        yield {"event": "session", "data": json.dumps({"session_id": session_id})}
        state = _build_chat_state(req.message, session_id)

        try:
            async for event in _stream_chat_run(
                state=state,
                session_id=session_id,
                recursion_limit=settings.recursion_limit,
                allow_pause=True,
            ):
                yield event

        except Exception as exc:
            logger.exception("Erro no stream de chat: %s", exc)
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(generate())


@app.post("/v1/chat/decision/stream")
async def chat_decision_stream(req: ChatDecisionRequest):
    from hughie.config import get_settings

    settings = get_settings()
    pending = _pending_chats.get(req.session_id)
    if pending is None:
        return JSONResponse(status_code=404, content={"detail": "No pending approval for this session"})

    decision = req.decision.strip().lower()
    if decision not in {"continue", "respond_now", "approve", "deny"}:
        return JSONResponse(status_code=400, content={"detail": "Invalid decision"})

    message = pending["message"]
    _pending_chats.pop(req.session_id, None)

    if pending["type"] == "tool_confirmation":
        approved = decision == "approve"
        register_decision(req.session_id, pending["action_key"], approved)
        if approved:
            message = (
                f"{message}\n\n"
                "IMPORTANTE: o usuário já autorizou a ação sensível pendente. "
                "Se ela ainda for necessária, execute a ação aprovada diretamente sem pedir confirmação de novo."
            )
        else:
            message = (
                f"{message}\n\n"
                "IMPORTANTE: o usuário negou a ação sensível pendente. "
                "Não tente executá-la novamente. Responda explicando brevemente que a ação foi negada "
                "e, se fizer sentido, ofereça uma alternativa sem escrita ou execução sensível."
            )
        recursion_limit = settings.recursion_limit
        allow_pause = True
    elif decision == "respond_now":
        message = (
            f"{message}\n\n"
            "IMPORTANTE: pare a exploração extensa e responda agora usando somente o que já for possível concluir. "
            "Se algo ainda depender de investigação adicional, diga isso de forma breve."
        )
        recursion_limit = max(12, settings.recursion_limit // 2)
        allow_pause = False
    else:
        recursion_limit = settings.recursion_limit * 2
        allow_pause = True

    async def generate():
        yield {"event": "session", "data": json.dumps({"session_id": req.session_id})}
        try:
            async for event in _stream_chat_run(
                state=_build_chat_state(message, req.session_id),
                session_id=req.session_id,
                recursion_limit=recursion_limit,
                allow_pause=allow_pause,
            ):
                yield event
        except Exception as exc:
            logger.exception("Erro no stream de decisão: %s", exc)
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(generate())


@app.get("/v1/brain/notes/{note_id}")
async def get_note(note_id: str):
    note = await brain_store.get_note_by_id(note_id)
    if note is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return {
        "id": note.id,
        "title": note.title,
        "type": note.type,
        "importance": note.importance,
        "status": note.status,
        "content": note.content,
        "updated_at": note.updated_at.isoformat(),
    }


@app.patch("/v1/brain/notes/{note_id}")
async def update_note(note_id: str, req: NoteUpdateRequest):
    note = await brain_store.update_note(
        note_id,
        req.content,
        title=req.title,
        note_type=req.type,
        importance=req.importance,
        status=req.status,
        source_kind="manual_admin",
    )
    if note is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return {
        "id": note.id,
        "title": note.title,
        "type": note.type,
        "importance": note.importance,
        "status": note.status,
        "content": note.content,
        "updated_at": note.updated_at.isoformat(),
    }


@app.delete("/v1/brain/notes/{note_id}")
async def delete_note(note_id: str):
    deleted = await brain_store.delete_note(note_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return {"ok": True}


@app.get("/v1/brain/notes")
async def list_notes(note_type: str = Query(""), limit: int = Query(50)):
    notes = await brain_store.list_notes(limit=limit)
    if note_type:
        notes = [n for n in notes if n.type == note_type]
    return [
        {
            "id": n.id,
            "title": n.title,
            "type": n.type,
            "importance": n.importance,
            "status": n.status,
            "content": n.content,
            "updated_at": n.updated_at.isoformat(),
        }
        for n in notes
    ]


@app.get("/v1/brain/search")
async def search_notes(q: str = Query(...), limit: int = Query(5)):
    notes = await brain_store.search_notes(q, limit=limit)
    return [
        {
            "id": n.id,
            "title": n.title,
            "type": n.type,
            "importance": n.importance,
            "content": n.content,
        }
        for n in notes
    ]


@app.get("/v1/brain/graph")
async def brain_graph():
    notes = await brain_store.list_notes(limit=500)
    links = await link_store.list_all_links(limit=2000)
    nodes = [
        {
            "id": n.id,
            "label": n.title,
            "type": n.type or "fact",
            "importance": n.importance,
            "status": n.status,
        }
        for n in notes
    ]
    edges = []
    for lnk in links:
        if lnk.target_kind == "note" and lnk.target_note_id:
            edges.append({
                "source": lnk.source_note_id,
                "target": lnk.target_note_id,
                "relation": lnk.relation_type,
                "weight": lnk.weight,
            })
        elif lnk.target_kind in {"file", "directory"} and lnk.target_path:
            path_id = f"path:{lnk.target_path}"
            if not any(n["id"] == path_id for n in nodes):
                name = lnk.target_path.split("/")[-1] or lnk.target_path
                nodes.append({"id": path_id, "label": name, "type": lnk.target_kind, "importance": 0.5, "status": "active"})
            edges.append({
                "source": lnk.source_note_id,
                "target": path_id,
                "relation": lnk.relation_type,
                "weight": lnk.weight,
            })
    return {"nodes": nodes, "edges": edges}


@app.get("/v1/sessions")
async def list_sessions(limit: int = Query(30)):
    sessions = await conversation_store.list_sessions(limit=limit)
    return [
        {
            "session_id": s["session_id"],
            "message_count": s["message_count"],
            "last_at": s["last_at"].isoformat(),
            "last_message": (s["last_message"] or "")[:120],
        }
        for s in sessions
    ]


@app.get("/v1/sessions/{session_id}")
async def get_session_messages(session_id: str):
    turns = await conversation_store.get_recent(session_id, limit=200)
    return [
        {
            "role": t.role,
            "content": t.content,
            "created_at": t.created_at.isoformat(),
        }
        for t in turns
    ]


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = await conversation_store.delete_session(session_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return {"ok": True}
