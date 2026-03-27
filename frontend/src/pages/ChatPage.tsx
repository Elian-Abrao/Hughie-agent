import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { streamChat, fetchSessions, fetchSessionMessages, checkHealth } from "../api/client";
import type { Session } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";
import { useChatStore } from "../store/chatStore";
import type { Message } from "../store/chatStore";
import { IconPlus, IconSend } from "../components/Icons";

// ── Helpers ────────────────────────────────────────────────────────────────────

function uid() { return Math.random().toString(36).slice(2, 10); }

function reltime(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60_000);
  if (m < 1) return "agora";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

type Status = "online" | "typing" | "offline";

// ── Component ──────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { sessionId, messages, setSessionId, setMessages, appendMessages, updateMessage, reset } =
    useChatStore();

  const [sessions, setSessions] = useState<Session[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState<Status>("offline");

  const sessionIdRef = useRef(sessionId);
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const loadSessions = useCallback(async () => setSessions(await fetchSessions()), []);

  useEffect(() => {
    loadSessions();
    checkHealth().then((ok) => setStatus(ok ? "online" : "offline"));
    const t = setInterval(
      () => checkHealth().then((ok) => setStatus((s) => (s === "typing" ? s : ok ? "online" : "offline"))),
      30_000
    );
    return () => clearInterval(t);
  }, [loadSessions]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const openSession = useCallback(async (id: string) => {
    setSessionId(id);
    const turns = await fetchSessionMessages(id);
    setMessages(
      turns.map((t) => ({
        id: uid(),
        role: t.role,
        content: t.content,
        tools: [],
        streaming: false,
        error: false,
      }))
    );
  }, [setSessionId, setMessages]);

  const newSession = useCallback(() => {
    abortRef.current?.abort();
    reset();
    sessionIdRef.current = "";
    setInput("");
    textareaRef.current?.focus();
  }, [reset]);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    if (textareaRef.current) { textareaRef.current.style.height = "auto"; }

    const assistantId = uid();
    appendMessages([
      { id: uid(), role: "user",      content: text, tools: [], streaming: false, error: false },
      { id: assistantId, role: "assistant", content: "", tools: [], streaming: true,  error: false },
    ]);
    setStreaming(true);
    setStatus("typing");

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      for await (const ev of streamChat(text, sessionIdRef.current, ctrl.signal)) {
        if (ev.event === "session" && !sessionIdRef.current) {
          sessionIdRef.current = ev.data.session_id;
          setSessionId(ev.data.session_id);
        } else if (ev.event === "text") {
          updateMessage(assistantId, (m) => ({ ...m, content: m.content + ev.data.text }));
        } else if (ev.event === "tool") {
          updateMessage(assistantId, (m) => ({ ...m, tools: [...m.tools, ev.data.tool] }));
        } else if (ev.event === "error") {
          updateMessage(assistantId, (m) => ({ ...m, content: `Erro: ${ev.data.error}`, streaming: false, error: true }));
          break;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        updateMessage(assistantId, (m) => ({ ...m, content: "Falha na conexão.", streaming: false, error: true }));
      }
    }

    updateMessage(assistantId, (m) => ({ ...m, streaming: false }));
    setStreaming(false);
    setStatus("online");
    loadSessions();
    textareaRef.current?.focus();
  }, [input, streaming, appendMessages, updateMessage, setSessionId, loadSessions]);

  return (
    <div className="flex h-full">
      {/* ── Sessions sidebar ── */}
      <div className="w-[188px] flex-shrink-0 border-r border-border bg-surface flex flex-col">
        <div className="p-2 border-b border-border">
          <button
            onClick={newSession}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-muted hover:text-[#d8d8f0] hover:bg-surface2 transition-colors"
          >
            <IconPlus size={14} />
            <span>Nova sessão</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
          {sessions.length === 0 && (
            <p className="text-xs text-muted px-3 pt-3">Sem histórico</p>
          )}
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => openSession(s.session_id)}
              className={clsx(
                "w-full text-left px-3 py-2.5 rounded-lg transition-colors group",
                s.session_id === sessionId
                  ? "bg-accent-dim border border-[#3a308a]"
                  : "hover:bg-surface2"
              )}
            >
              <div className="flex items-center justify-between gap-1 mb-0.5">
                <span className={clsx("text-xs font-mono truncate", s.session_id === sessionId ? "text-accent" : "text-muted-2")}>
                  {s.session_id.slice(0, 11)}
                </span>
                <span className="text-[10px] text-muted flex-shrink-0">{reltime(s.last_at)}</span>
              </div>
              <p className="text-[11px] text-muted truncate leading-tight">{s.last_message}</p>
            </button>
          ))}
        </div>
      </div>

      {/* ── Chat area ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header bar */}
        <div className="h-12 flex items-center justify-between px-5 border-b border-border flex-shrink-0 bg-surface/60 backdrop-blur-sm">
          <span className="text-xs font-mono text-muted">
            {sessionId ? `sess: ${sessionId.slice(0, 18)}` : "nova sessão"}
          </span>
          <div className="flex items-center gap-2">
            <span className={clsx("text-xs", status === "typing" ? "text-accent" : status === "online" ? "text-green-400" : "text-muted")}>
              {status === "typing" ? "pensando…" : status === "online" ? "online" : "offline"}
            </span>
            <div className={clsx("w-1.5 h-1.5 rounded-full", {
              "bg-green-400": status === "online",
              "bg-accent animate-pulse": status === "typing",
              "bg-muted": status === "offline",
            })} />
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto py-8">
          {messages.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="max-w-2xl mx-auto px-5 space-y-6">
              {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="px-5 pb-5 pt-3 flex-shrink-0 border-t border-border/50 bg-surface/40 backdrop-blur-sm">
          <div className="max-w-2xl mx-auto flex gap-3 items-end">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                rows={1}
                disabled={streaming}
                onChange={(e) => { setInput(e.target.value); autoResize(e.target); }}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder="Mensagem… (Shift+Enter para nova linha)"
                className={clsx(
                  "w-full bg-surface2 border rounded-xl text-sm text-[#d8d8f0] placeholder-muted",
                  "resize-none outline-none px-4 py-3 leading-relaxed transition-all",
                  "min-h-[46px] max-h-[200px] font-sans",
                  streaming ? "opacity-60 cursor-not-allowed border-border" : "border-border focus:border-accent focus:ring-1 focus:ring-accent/30"
                )}
              />
            </div>
            <button
              onClick={send}
              disabled={streaming || !input.trim()}
              className={clsx(
                "w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0",
                "transition-all duration-150",
                streaming || !input.trim()
                  ? "bg-surface2 border border-border text-muted cursor-not-allowed"
                  : "bg-accent hover:bg-accent-h text-white shadow-[0_0_12px_rgba(124,106,247,0.4)] hover:shadow-[0_0_18px_rgba(124,106,247,0.6)]"
              )}
            >
              <IconSend size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8 animate-fadein">
      <div className="w-20 h-20 rounded-2xl bg-accent-dim border border-[#3a308a] flex items-center justify-center mb-5 shadow-[0_0_24px_rgba(124,106,247,0.2)] overflow-hidden">
        <img src="/Hughie.svg" alt="Hughie" className="w-full h-full object-contain" />
      </div>
      <h2 className="text-[#d8d8f0] font-semibold text-base mb-1.5">Olá, sou o Hughie</h2>
      <p className="text-muted text-sm max-w-xs leading-relaxed">
        Seu agente pessoal persistente. Tenho memória e posso acessar seus ambientes remotamente.
      </p>
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  return (
    <div className={clsx("flex gap-3 animate-fadein", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div className={clsx(
        "w-7 h-7 rounded-lg flex-shrink-0 flex items-center justify-center text-xs font-bold mt-0.5",
        isUser
          ? "bg-[#1a3520] text-green-400 border border-[#253525]"
          : "bg-accent-dim text-accent border border-[#3a308a]"
      )}>
        {isUser ? "E" : "H"}
      </div>

      {/* Content */}
      <div className={clsx("flex flex-col gap-2 min-w-0", isUser ? "items-end max-w-[80%]" : "flex-1")}>
        {/* Tool calls */}
        {msg.tools.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {msg.tools.map((t, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 text-[11px] bg-tool-bg text-tool-text border border-[#2a2a50] rounded-full px-2.5 py-0.5 font-mono">
                <span className="opacity-60">⚙</span> {t}
              </span>
            ))}
          </div>
        )}

        {/* Bubble */}
        <div className={clsx(
          "rounded-2xl text-sm leading-relaxed",
          isUser
            ? "bg-user-bg border border-user-border rounded-tr-sm px-4 py-3 text-[#d8d8f0]"
            : clsx(
                "px-4 py-3 rounded-tl-sm w-full",
                msg.error
                  ? "bg-red-950/40 border border-red-900/50 text-red-300"
                  : "bg-surface2 border border-border/80"
              )
        )}>
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
          ) : (
            <>
              {msg.content
                ? <MarkdownContent content={msg.content} />
                : msg.streaming
                  ? <span className="text-muted text-xs italic">pensando…</span>
                  : null}
              {msg.streaming && msg.content && (
                <span className="inline-block w-0.5 h-[0.9em] bg-accent ml-0.5 animate-blink align-middle rounded-sm" />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
