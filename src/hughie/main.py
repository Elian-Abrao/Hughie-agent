import asyncio
import getpass
import uuid
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Hughie — seu agente pessoal", no_args_is_help=True)
brain_app = typer.Typer(help="Gerenciar brain notes")
db_app = typer.Typer(help="Comandos de banco de dados")
host_agent_app = typer.Typer(help="Serviço persistente para acesso rápido ao host principal")
app.add_typer(brain_app, name="brain")
app.add_typer(db_app, name="db")
app.add_typer(host_agent_app, name="host-agent")

console = Console()


async def _chat_session(session_id: str, no_stream: bool) -> None:
    from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage
    from hughie.config import get_settings
    from hughie.core.graph import build_graph
    from hughie.llm.broker_runtime import ensure_broker_ready
    from hughie.core.nodes import init_llm
    from hughie.memory.database import run_migrations, close_pool
    from hughie.tools.mcp_loader import close_mcp_client
    from hughie.tools.registry import load_all_tools

    broker_started = await ensure_broker_ready()
    settings = get_settings()
    if broker_started:
        console.print("[dim]llm-broker iniciado automaticamente.[/dim]")

    await run_migrations()
    tools = await load_all_tools()
    init_llm(tools)
    graph = build_graph(tools)

    if session_id:
        console.print(f"[dim]Sessão: {session_id}[/dim]")
    console.print("[dim]Digite 'exit' ou pressione Ctrl+C para sair.[/dim]\n")

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: console.input("[bold cyan]Você:[/bold cyan] ").strip()
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Até mais![/dim]")
                break

            if user_input.lower() in ("exit", "quit", "sair"):
                console.print("[dim]Até mais![/dim]")
                break

            if not user_input:
                continue

            initial_state = {
                "messages": [HumanMessage(content=user_input)],
                "history": [],
                "session_id": session_id,
                "brain_context": "",
            }

            console.print("[bold green]Hughie:[/bold green] ", end="")

            try:
                if no_stream:
                    result = await graph.ainvoke(initial_state, {"recursion_limit": settings.recursion_limit})
                    for msg in reversed(result["messages"]):
                        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                            console.print(msg.content)
                            break
                else:
                    async for chunk, metadata in graph.astream(
                        initial_state,
                        stream_mode="messages",
                        config={"recursion_limit": settings.recursion_limit},
                    ):
                        if (
                            isinstance(chunk, AIMessageChunk)
                            and metadata.get("langgraph_node") == "chat"
                            and chunk.content
                            and not getattr(chunk, "tool_call_chunks", None)
                        ):
                            print(chunk.content, end="", flush=True)
                    print()
            except Exception as e:
                console.print(f"\n[red]Erro: {e}[/red]")

            console.print()
    finally:
        await close_mcp_client()
        await close_pool()


@app.command()
def chat(
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Nome da sessão (persiste entre runs)"),
    no_stream: bool = typer.Option(False, "--no-stream", help="Desativar streaming"),
):
    """Iniciar conversa interativa com o Hughie."""
    session_id = session or getpass.getuser()
    asyncio.run(_chat_session(session_id, no_stream))


@brain_app.command("list")
def brain_list():
    """Listar todas as brain notes."""
    from hughie.memory import brain_store

    notes = asyncio.run(brain_store.list_notes())
    if not notes:
        console.print("[dim]Nenhuma brain note encontrada.[/dim]")
        return

    table = Table(title="Brain Notes")
    table.add_column("ID", style="dim", width=36)
    table.add_column("Tipo", style="cyan", width=12)
    table.add_column("Título", style="bold")
    table.add_column("Conteúdo")
    table.add_column("Atualizado", style="dim", width=20)

    for n in notes:
        table.add_row(
            str(n.id),
            n.type,
            n.title,
            n.content[:80] + "..." if len(n.content) > 80 else n.content,
            n.updated_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@brain_app.command("search")
def brain_search(query: str = typer.Argument(..., help="Texto para busca semântica")):
    """Buscar brain notes por similaridade semântica."""
    from hughie.memory import brain_store

    notes = asyncio.run(brain_store.search_notes(query))
    if not notes:
        console.print("[dim]Nenhuma nota relevante encontrada.[/dim]")
        return

    for n in notes:
        console.print(f"[cyan][{n.type}][/cyan] [bold]{n.title}[/bold]")
        console.print(f"  {n.content}")
        console.print(f"  [dim]{n.id}[/dim]\n")


@brain_app.command("delete")
def brain_delete(note_id: str = typer.Argument(..., help="UUID da nota")):
    """Remover uma brain note pelo ID."""
    from hughie.memory import brain_store

    deleted = asyncio.run(brain_store.delete_note(note_id))
    if deleted:
        console.print(f"[green]Nota {note_id} removida.[/green]")
    else:
        console.print(f"[red]Nota {note_id} não encontrada.[/red]")


@brain_app.command("consolidate")
def brain_consolidate(
    session_id: str | None = typer.Argument(None, help="Session ID para consolidar"),
    hint: str = typer.Option("", "--hint", help="Foco especial para a consolidação"),
):
    """Executar consolidação manual de uma sessão."""
    from hughie.memory import conversation_store
    from hughie.memory.consolidator import run_consolidation

    target_session_id = session_id
    if not target_session_id:
        sessions = asyncio.run(conversation_store.list_sessions(limit=1))
        if not sessions:
            console.print("[red]Nenhuma sessão encontrada para consolidar.[/red]")
            raise typer.Exit(code=1)
        target_session_id = str(sessions[0]["session_id"])

    console.print(f"[dim]Consolidando sessão {target_session_id}...[/dim]")
    count = asyncio.run(run_consolidation(target_session_id, hint=hint))
    console.print(f"[green]Consolidação concluída. {count} nota(s) atualizadas.[/green]")


@brain_app.command("maintain")
def brain_maintain():
    """Executar manutenção do grafo e memória."""
    from hughie.memory.maintenance import run_all

    console.print("[dim]Executando manutenção do grafo...[/dim]")
    result = asyncio.run(run_all())
    console.print(
        "[green]Manutenção concluída.[/green] "
        f"decayed={result['decayed']} gc={result['garbage_collected']} conflicts={result['conflicts_resolved']}"
    )


@db_app.command("migrate")
def db_migrate():
    """Rodar migrations do banco de dados."""
    from hughie.memory.database import run_migrations_sync

    console.print("[dim]Rodando migrations...[/dim]")
    run_migrations_sync()
    console.print("[green]Migrations concluídas.[/green]")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Endereço de bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Porta"),
    reload: bool = typer.Option(False, "--reload", help="Hot-reload (dev)"),
):
    """Iniciar o servidor HTTP da API do Hughie."""
    import uvicorn
    console.print(f"[dim]Iniciando Hughie API em http://{host}:{port}[/dim]")
    uvicorn.run(
        "hughie.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def config():
    """Exibir configuração atual."""
    from hughie.config import get_settings

    s = get_settings()
    table = Table(title="Configuração do Hughie")
    table.add_column("Chave", style="cyan")
    table.add_column("Valor")

    table.add_row("database_url", s.database_url)
    table.add_row("bridge_url", s.bridge_url)
    table.add_row("bridge_model", s.bridge_model)
    table.add_row("bridge_timeout", str(s.bridge_timeout))
    table.add_row("host_agent_url", s.host_agent_url or "[dim]não configurado[/dim]")
    table.add_row("google_api_key", "***" if s.google_api_key else "[red]não configurado[/red]")

    console.print(table)


@host_agent_app.command("serve")
def host_agent_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Endereço de bind"),
    port: int = typer.Option(8787, "--port", help="Porta"),
):
    """Iniciar o host-agent persistente para acesso rápido ao sistema local."""
    import uvicorn

    console.print(f"[dim]Iniciando Hughie host-agent em http://{host}:{port}[/dim]")
    uvicorn.run(
        "hughie.host_agent.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
