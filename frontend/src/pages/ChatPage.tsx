import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { streamChat } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";
import { IconSend } from "../components/Icons";
import { useChatStore } from "../store/chatStore";
import type { Message } from "../store/chatStore";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export default function ChatPage() {
  const { sessionId, messages, setSessionId, appendMessages, updateMessage } = useChatStore();

  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);

  const sessionIdRef = useRef(sessionId);
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const assistantId = uid();
    appendMessages([
      { id: uid(), role: "user", content: text, tools: [], streaming: false, error: false },
      { id: assistantId, role: "assistant", content: "", tools: [], streaming: true, error: false },
    ]);
    setStreaming(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      for await (const ev of streamChat(text, sessionIdRef.current, ctrl.signal)) {
        if (ev.event === "session" && !sessionIdRef.current) {
          sessionIdRef.current = ev.data.session_id;
          setSessionId(ev.data.session_id);
        } else if (ev.event === "text") {
          updateMessage(assistantId, (msg) => ({ ...msg, content: msg.content + ev.data.text }));
        } else if (ev.event === "tool") {
          updateMessage(assistantId, (msg) => ({ ...msg, tools: [...msg.tools, ev.data.tool] }));
        } else if (ev.event === "error") {
          updateMessage(assistantId, (msg) => ({
            ...msg,
            content: `Erro: ${ev.data.error}`,
            streaming: false,
            error: true,
          }));
          break;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: "Falha na conexão.",
          streaming: false,
          error: true,
        }));
      }
    }

    updateMessage(assistantId, (msg) => ({ ...msg, streaming: false }));
    setStreaming(false);
    window.dispatchEvent(new Event("hughie:sessions-refresh"));
    textareaRef.current?.focus();
  }, [appendMessages, input, setSessionId, streaming, updateMessage]);

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="h-12 flex items-center justify-between border-b border-border bg-surface px-5">
          <div className="min-w-0">
            <span className="block text-[10px] uppercase tracking-[0.18em] text-muted">Chat</span>
            <span className="block truncate font-mono text-xs text-muted-2">
              {sessionId ? `sess: ${sessionId.slice(0, 18)}` : "nova sessão"}
            </span>
          </div>
          {streaming ? (
            <span className="text-xs text-accent">pensando…</span>
          ) : (
            <span className="text-xs text-muted">Hughie</span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto py-8">
          {messages.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="mx-auto max-w-2xl space-y-6 px-5">
              {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <div className="border-t border-border/50 bg-surface px-5 pb-5 pt-3">
          <div className="mx-auto flex max-w-2xl items-end gap-3">
            <div className="relative flex-1">
              <textarea
                ref={textareaRef}
                value={input}
                rows={1}
                disabled={streaming}
                onChange={(e) => {
                  setInput(e.target.value);
                  autoResize(e.target);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder="Mensagem… (Shift+Enter para nova linha)"
                className={clsx(
                  "min-h-[46px] max-h-[200px] w-full resize-none rounded-2xl border bg-surface2 px-4 py-3 font-sans text-sm leading-relaxed text-text outline-none transition-all placeholder:text-muted",
                  streaming
                    ? "cursor-not-allowed border-border opacity-60"
                    : "border-border focus:border-accent"
                )}
              />
            </div>
            <button
              onClick={() => void send()}
              disabled={streaming || !input.trim()}
              className={clsx(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl transition-all duration-150",
                streaming || !input.trim()
                  ? "cursor-not-allowed border border-border bg-surface2 text-muted"
                  : "border border-accent bg-accent text-white hover:bg-accent-h"
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

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center animate-fadein">
      <img
        src="/Hughie.svg"
        alt="Hughie"
        className="mb-2 h-52 w-52 object-contain"
      />
      <h2 className="mb-1.5 text-base font-semibold text-strong">Olá, sou o Hughie</h2>
      <p className="max-w-xs text-sm leading-relaxed text-muted">
        Seu agente pessoal persistente. Tenho memória e posso acessar seus ambientes remotamente.
      </p>
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  return (
    <div className={clsx("flex gap-3 animate-fadein", isUser && "flex-row-reverse")}>
      <div
        className={clsx(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border text-xs font-bold",
          isUser
            ? "border-user-border bg-user-bg text-accent"
            : "border-accent/25 bg-accent-dim text-accent"
        )}
      >
        {isUser ? (
          "E"
        ) : (
          <img src="/Hughie.svg" alt="Hughie" className="h-5 w-5 object-contain" />
        )}
      </div>

      <div className={clsx("flex min-w-0 flex-col gap-2", isUser ? "max-w-[80%] items-end" : "flex-1")}>
        {msg.tools.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {msg.tools.map((tool, index) => (
              <span
                key={`${tool}-${index}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-accent/15 bg-tool-bg px-2.5 py-0.5 font-mono text-[11px] text-tool-text"
              >
                <span className="opacity-60">⚙</span> {tool}
              </span>
            ))}
          </div>
        )}

        <div
          className={clsx(
            "rounded-2xl text-sm leading-relaxed",
            isUser
              ? "rounded-tr-sm border border-user-border bg-user-bg px-4 py-3 text-text"
              : clsx(
                  "w-full rounded-tl-sm border px-4 py-3",
                  msg.error
                    ? "border-red-900/50 bg-red-950/40 text-red-300"
                    : "border-border/80 bg-surface2"
                )
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
          ) : (
            <>
              {msg.content ? (
                <MarkdownContent content={msg.content} />
              ) : msg.streaming ? (
                <span className="text-xs italic text-muted">pensando…</span>
              ) : null}
              {msg.streaming && msg.content && (
                <span className="ml-0.5 inline-block h-[0.9em] w-0.5 animate-blink rounded-sm bg-accent align-middle" />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
