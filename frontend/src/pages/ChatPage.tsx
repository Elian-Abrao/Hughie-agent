import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import {
  streamChat,
  fetchSessions,
  fetchSessionMessages,
  checkHealth,
} from "../api/client";
import type { Session } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: string[];
  streaming: boolean;
  error: boolean;
}

type Status = "online" | "typing" | "offline";

// ── Helpers ───────────────────────────────────────────────────────────────────

function uid() {
  return Math.random().toString(36).slice(2);
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "agora";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState<Status>("offline");

  const sessionIdRef = useRef(sessionId);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Keep ref in sync with state (needed inside async generator)
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const loadSessions = useCallback(async () => {
    setSessions(await fetchSessions());
  }, []);

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
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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
  }, []);

  const newSession = useCallback(() => {
    abortRef.current?.abort();
    setSessionId("");
    sessionIdRef.current = "";
    setMessages([]);
    setInput("");
    textareaRef.current?.focus();
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px";
  };

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const assistantId = uid();

    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: text, tools: [], streaming: false, error: false },
      { id: assistantId, role: "assistant", content: "", tools: [], streaming: true, error: false },
    ]);
    setIsStreaming(true);
    setStatus("typing");

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      for await (const ev of streamChat(text, sessionIdRef.current, abort.signal)) {
        if (ev.event === "session" && !sessionIdRef.current) {
          sessionIdRef.current = ev.data.session_id;
          setSessionId(ev.data.session_id);
        } else if (ev.event === "text") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + ev.data.text } : m
            )
          );
        } else if (ev.event === "tool") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, tools: [...m.tools, ev.data.tool] } : m
            )
          );
        } else if (ev.event === "error") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `Erro: ${ev.data.error}`, streaming: false, error: true }
                : m
            )
          );
          break;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: "Falha na conexão.", streaming: false, error: true }
              : m
          )
        );
      }
    }

    setMessages((prev) =>
      prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m))
    );
    setIsStreaming(false);
    setStatus("online");
    loadSessions();
    textareaRef.current?.focus();
  }, [input, isStreaming, loadSessions]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex h-full">
      {/* ── Sessions sidebar ── */}
      <div className="w-52 flex-shrink-0 border-r border-border bg-surface flex flex-col">
        <div className="p-2 border-b border-border">
          <button
            onClick={newSession}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted hover:text-[#e8e8e8] hover:bg-surface2 rounded-md transition-colors"
          >
            <span className="text-accent text-base leading-none">+</span>
            Nova sessão
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {sessions.length === 0 && (
            <p className="text-xs text-muted px-3 pt-3">Nenhuma sessão</p>
          )}
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => openSession(s.session_id)}
              className={clsx(
                "w-full text-left px-3 py-2 rounded-md transition-colors",
                s.session_id === sessionId
                  ? "bg-accent-dim text-[#e8e8e8]"
                  : "hover:bg-surface2 text-muted hover:text-[#e8e8e8]"
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-xs font-mono truncate">{s.session_id.slice(0, 12)}</span>
                <span className="text-[10px] text-muted flex-shrink-0">{relativeTime(s.last_at)}</span>
              </div>
              <p className="text-xs text-muted mt-0.5 truncate leading-tight">{s.last_message}</p>
            </button>
          ))}
        </div>
      </div>

      {/* ── Chat area ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-13 flex items-center justify-between px-5 border-b border-border flex-shrink-0">
          <span className="text-xs font-mono text-muted">
            {sessionId ? `sess: ${sessionId.slice(0, 16)}` : "nova sessão"}
          </span>
          <StatusDot status={status} />
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto py-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="text-5xl mb-4">🤖</div>
              <p className="text-[#e8e8e8] font-semibold mb-1">Olá, eu sou o Hughie</p>
              <p className="text-muted text-sm max-w-xs leading-relaxed">
                Seu agente pessoal persistente. Como posso ajudar?
              </p>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto px-4 space-y-5">
              {messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-border bg-surface px-4 py-3 flex-shrink-0">
          <div className="max-w-3xl mx-auto flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Mensagem… (Enter envia, Shift+Enter nova linha)"
              rows={1}
              disabled={isStreaming}
              className="flex-1 bg-surface2 border border-border rounded-xl text-sm text-[#e8e8e8] placeholder-muted resize-none outline-none px-4 py-3 leading-relaxed focus:border-accent transition-colors min-h-[46px] max-h-[180px] disabled:opacity-50"
            />
            <button
              onClick={send}
              disabled={isStreaming || !input.trim()}
              className="w-11 h-11 rounded-xl bg-accent flex items-center justify-center flex-shrink-0 transition-opacity hover:opacity-85 disabled:opacity-30 disabled:cursor-not-allowed"
              aria-label="Enviar"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="w-4 h-4 text-white"
              >
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: Status }) {
  return (
    <div
      className={clsx("w-2 h-2 rounded-full transition-colors", {
        "bg-green-500": status === "online",
        "bg-accent animate-pulse": status === "typing",
        "bg-muted": status === "offline",
      })}
    />
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={clsx("flex gap-3", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={clsx(
          "w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-sm font-bold mt-0.5",
          isUser ? "bg-user-border text-green-400" : "bg-accent-dim text-accent"
        )}
      >
        {isUser ? "E" : "H"}
      </div>

      {/* Content block */}
      <div className={clsx("flex flex-col gap-1.5 max-w-[78%]", isUser && "items-end")}>
        {/* Tool badges */}
        {message.tools.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {message.tools.map((tool, i) => (
              <span
                key={i}
                className="text-xs bg-tool-bg text-tool-text border border-[#2a2a4a] rounded-md px-2 py-0.5 font-mono"
              >
                ⚙ {tool}
              </span>
            ))}
          </div>
        )}

        {/* Bubble */}
        <div
          className={clsx(
            "px-4 py-3 rounded-2xl text-sm leading-relaxed",
            isUser
              ? "bg-user-bg border border-user-border rounded-tr-sm text-[#e8e8e8]"
              : clsx(
                  "bg-surface2 border rounded-tl-sm",
                  message.error ? "border-red-800 text-red-400" : "border-border"
                )
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <>
              {message.content ? (
                <MarkdownContent content={message.content} />
              ) : message.streaming ? (
                <span className="text-muted text-xs italic">pensando…</span>
              ) : null}
              {message.streaming && message.content && (
                <span className="inline-block w-0.5 h-[1em] bg-accent ml-0.5 animate-blink align-middle" />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
