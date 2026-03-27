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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from hughie.core.graph import build_graph
from hughie.core.nodes import init_llm
from hughie.llm.broker_runtime import ensure_broker_ready
from hughie.memory import brain_store, conversation_store, link_store
from hughie.memory.database import close_pool, run_migrations
from hughie.tools.mcp_loader import close_mcp_client
from hughie.tools.registry import load_all_tools

logger = logging.getLogger(__name__)

_graph = None


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "service": "hughie"}


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    state = {
        "messages": [HumanMessage(content=req.message)],
        "history": [],
        "session_id": session_id,
        "brain_context": "",
    }
    result = await _graph.ainvoke(state)
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            return {"reply": msg.content, "session_id": session_id}
    return {"reply": "", "session_id": session_id}


@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    async def generate():
        # Confirm session_id first so client can track it
        yield {"event": "session", "data": json.dumps({"session_id": session_id})}

        state = {
            "messages": [HumanMessage(content=req.message)],
            "history": [],
            "session_id": session_id,
            "brain_context": "",
        }

        try:
            async for chunk, metadata in _graph.astream(state, stream_mode="messages"):
                node = metadata.get("langgraph_node", "")

                if (
                    isinstance(chunk, AIMessageChunk)
                    and node == "chat"
                    and chunk.content
                    and not getattr(chunk, "tool_call_chunks", None)
                ):
                    yield {"event": "text", "data": json.dumps({"text": chunk.content})}

                elif node == "tools":
                    # Notify client that a tool is running
                    tool_name = getattr(chunk, "name", None)
                    if tool_name:
                        yield {"event": "tool", "data": json.dumps({"tool": tool_name})}

        except Exception as exc:
            logger.exception("Erro no stream de chat: %s", exc)
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(generate())


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
