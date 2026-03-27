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
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from hughie.approvals import ApprovalRequired, approval_context, grant_scope, register_decision
from hughie.config import get_settings
from hughie.core.graph import build_graph
from hughie.core.nodes import init_llm
from hughie.llm.broker_runtime import ensure_broker_ready
from hughie.memory import brain_store, conversation_store, episode_store, link_store
from hughie.memory.database import close_pool, get_pool, run_migrations
from hughie.memory.maintenance import run_all as run_maintenance
from hughie.scheduler import start_scheduler, stop_scheduler
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
    start_scheduler()
    logger.info("Hughie API pronta.")
    yield
    await stop_scheduler()
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
    fonte: str = "input_manual"
    confianca: float | None = None
    peso_temporal: float = 1.0
    criado_por: str = "manual_admin"
    metadados: dict[str, Any] = {}


class NoteCreateRequest(NoteUpdateRequest):
    pass


def _serialize_note(note: brain_store.BrainNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "title": note.title,
        "type": note.type,
        "importance": note.importance,
        "status": note.status,
        "content": note.content,
        "fonte": note.fonte,
        "confianca": note.confianca,
        "peso_temporal": note.peso_temporal,
        "criado_por": note.criado_por,
        "ultima_atualizacao": note.ultima_atualizacao.isoformat(),
        "historico": note.historico,
        "metadados": note.metadados,
        "updated_at": note.updated_at.isoformat(),
        "created_at": note.created_at.isoformat(),
    }


def _serialize_episode(episode: episode_store.Episode) -> dict[str, Any]:
    return {
        "id": episode.id,
        "session_id": episode.session_id,
        "created_at": episode.created_at.isoformat(),
        "tarefa": episode.tarefa,
        "resultado": episode.resultado,
        "tempo_total_segundos": episode.tempo_total_segundos,
        "arquivos_modificados": episode.arquivos_modificados,
        "decisoes_tomadas": episode.decisoes_tomadas,
        "erros_encontrados": episode.erros_encontrados,
        "aprendizados": episode.aprendizados,
        "node_ids_afetados": episode.node_ids_afetados,
    }


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


def _extract_candidate_paths(message: str, prefixes: list[str]) -> list[str]:
    paths = re.findall(r"(/[^\s\"'`]+)", message)
    seen: list[str] = []
    for path in paths:
        normalized = path.rstrip(".,:;)")
        if any(normalized.startswith(prefix) for prefix in prefixes) and normalized not in seen:
            seen.append(normalized)
    return seen[:4]


def _maybe_build_preflight_approval(message: str, session_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    lowered = message.lower()
    broad_keywords = ("todos", "todas", "subpastas", "varra", "busque", "procure", "analise", "entenda", "mapeie", "navegue", "percorra")
    if not any(keyword in lowered for keyword in broad_keywords):
        return None

    candidate_paths = _extract_candidate_paths(message, settings.local_machine_path_prefixes)
    if not candidate_paths:
        return None

    scope_keys: list[str] = []
    lines: list[str] = []
    for path in candidate_paths:
        scope_keys.append(f"ssh_exec_prefix|{settings.local_machine_host}|{path}")
        lines.append(f"- analisar arquivos e subpastas em `{path}`")

    _pending_chats[session_id] = {
        "type": "preflight_permissions",
        "message": message,
        "scope_keys": scope_keys,
    }
    return _approval_event(
        session_id=session_id,
        message=(
            "Para fazer isso direito, Hughie provavelmente vai precisar:\n"
            + "\n".join(lines)
            + "\n\nSe você autorizar agora, ele pode seguir nesses diretórios sem te interromper a cada comando."
        ),
        approve_label="Autorizar acesso inicial",
        reject_label="Responder sem acessar",
        approve_decision="approve",
        reject_decision="deny",
    )


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
            "scope_key": approval.scope_key,
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
        preflight = _maybe_build_preflight_approval(req.message, session_id)
        if preflight is not None:
            yield preflight
            yield {"event": "done", "data": "{}"}
            return
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
        if approved and pending.get("scope_key"):
            grant_scope(req.session_id, pending["scope_key"])
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
    elif pending["type"] == "preflight_permissions":
        if decision == "approve":
            for scope_key in pending.get("scope_keys", []):
                grant_scope(req.session_id, scope_key)
            message = (
                f"{message}\n\n"
                "IMPORTANTE: o usuário já autorizou o acesso inicial aos diretórios citados. "
                "Você pode seguir com leitura, análise e comandos nesses diretórios sem pedir de novo a cada passo."
            )
            recursion_limit = settings.recursion_limit
            allow_pause = True
        else:
            message = (
                f"{message}\n\n"
                "IMPORTANTE: o usuário preferiu não autorizar um acesso inicial amplo. "
                "Responda com o que for possível sem navegar nesses diretórios e peça algo mais específico se realmente precisar."
            )
            recursion_limit = max(12, settings.recursion_limit // 2)
            allow_pause = False
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
    return _serialize_note(note)


@app.post("/v1/brain/notes")
async def create_note(req: NoteCreateRequest):
    note = await brain_store.create_note(
        title=req.title,
        content=req.content,
        note_type=req.type,
        importance=req.importance,
        status=req.status,
        source_kind="manual_admin",
        fonte=req.fonte,
        confianca=req.confianca,
        peso_temporal=req.peso_temporal,
        criado_por=req.criado_por,
        metadados=req.metadados,
        metadata=req.metadados,
    )
    return _serialize_note(note)


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
        fonte=req.fonte,
        confianca=req.confianca,
        peso_temporal=req.peso_temporal,
        criado_por=req.criado_por,
        metadados=req.metadados,
        metadata=req.metadados,
    )
    if note is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return _serialize_note(note)


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
    return [_serialize_note(n) for n in notes]


@app.get("/v1/brain/search")
async def search_notes(q: str = Query(...), limit: int = Query(5)):
    notes = await brain_store.search_notes(q, limit=limit)
    episodes = await episode_store.search_similar_episodes(q, top_k=limit)
    return {
        "notes": [_serialize_note(n) for n in notes],
        "episodes": [_serialize_episode(ep) for ep in episodes],
    }


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
            "fonte": n.fonte,
            "confianca": n.confianca,
            "peso_temporal": n.peso_temporal,
            "metadados": n.metadados,
        }
        for n in notes
    ]
    edges = []
    for lnk in links:
        if lnk.target_kind == "note" and lnk.target_note_id:
            edges.append({
                "source": lnk.source_note_id,
                "target": lnk.target_note_id,
                "relation": lnk.tipo_relacao or lnk.relation_type,
                "weight": lnk.weight,
                "confianca": lnk.confianca,
                "fonte": lnk.fonte,
                "tipo_relacao": lnk.tipo_relacao or lnk.relation_type,
                "criado_em": lnk.created_em.isoformat() if lnk.created_em else None,
            })
        elif lnk.target_kind in {"file", "directory"} and lnk.target_path:
            path_id = f"path:{lnk.target_path}"
            if not any(n["id"] == path_id for n in nodes):
                name = lnk.target_path.split("/")[-1] or lnk.target_path
                nodes.append({
                    "id": path_id,
                    "label": name,
                    "type": lnk.target_kind,
                    "importance": 0.5,
                    "status": "active",
                    "fonte": lnk.fonte,
                    "confianca": lnk.confianca,
                    "peso_temporal": 1.0,
                    "metadados": {"path": lnk.target_path},
                })
            edges.append({
                "source": lnk.source_note_id,
                "target": path_id,
                "relation": lnk.tipo_relacao or lnk.relation_type,
                "weight": lnk.weight,
                "confianca": lnk.confianca,
                "fonte": lnk.fonte,
                "tipo_relacao": lnk.tipo_relacao or lnk.relation_type,
                "criado_em": lnk.created_em.isoformat() if lnk.created_em else None,
            })
    return {"nodes": nodes, "edges": edges}


@app.get("/v1/brain/episodes")
async def list_episodes(limit: int = Query(20)):
    episodes = await episode_store.list_episodes(limit=limit)
    return [_serialize_episode(ep) for ep in episodes]


@app.get("/v1/brain/episodes/{episode_id}")
async def get_episode(episode_id: str):
    episode = await episode_store.get_episode(episode_id)
    if episode is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return _serialize_episode(episode)


@app.post("/v1/brain/maintain")
async def maintain_brain():
    return await run_maintenance()


@app.get("/v1/brain/stats")
async def brain_stats():
    notes = await brain_store.list_notes(limit=5000)
    links = await link_store.list_all_links(limit=10000)
    episodes = await episode_store.list_episodes(limit=5000)

    source_distribution: dict[str, int] = {}
    confidence_distribution = {"high": 0, "medium": 0, "low": 0}
    for note in notes:
        source_distribution[note.fonte] = source_distribution.get(note.fonte, 0) + 1
        if note.confianca >= 0.8:
            confidence_distribution["high"] += 1
        elif note.confianca >= 0.5:
            confidence_distribution["medium"] += 1
        else:
            confidence_distribution["low"] += 1

    latest_maintenance = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        latest_maintenance = await conn.fetchrow(
            """
            SELECT run_at, decayed, garbage_collected, conflicts_resolved
            FROM maintenance_runs
            ORDER BY run_at DESC
            LIMIT 1
            """
        )

    return {
        "total_nos": len(notes),
        "total_arestas": len(links),
        "distribuicao_por_fonte": source_distribution,
        "distribuicao_por_confianca": confidence_distribution,
        "episodios_criados": len(episodes),
        "ultimo_gc": latest_maintenance["run_at"].isoformat() if latest_maintenance else None,
        "ultima_manutencao": dict(latest_maintenance) if latest_maintenance else None,
    }


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
