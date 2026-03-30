import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { streamChat, streamChatDecision } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";
import { IconSend } from "../components/Icons";
import { useChatStore } from "../store/chatStore";
import type { Message } from "../store/chatStore";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export default function ChatPage() {
  const {
    sessionId,
    messages,
    pendingApproval,
    setSessionId,
    appendMessages,
    updateMessage,
    setPendingApproval,
  } = useChatStore();

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
      { id: uid(), role: "user", content: text, tools: [], activity: [], streaming: false, error: false },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        tools: [],
        activity: ["Pensando na melhor forma de responder."],
        streaming: true,
        error: false,
      },
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
          updateMessage(assistantId, (msg) => ({
            ...msg,
            content: msg.content + ev.data.text,
            activity: msg.activity.includes("Gerando resposta.")
              ? msg.activity
              : [...msg.activity, "Gerando resposta."],
          }));
        } else if (ev.event === "tool") {
          updateMessage(assistantId, (msg) => ({
            ...msg,
            tools: [...msg.tools, ev.data.tool],
            activity: [...msg.activity, `Tool chamada: ${ev.data.tool}`],
          }));
        } else if (ev.event === "approval") {
          setPendingApproval({
            assistantId,
            sessionId: ev.data.session_id,
            message: ev.data.message,
            approveLabel: ev.data.approve_label,
            rejectLabel: ev.data.reject_label,
            approveDecision: ev.data.approve_decision,
            rejectDecision: ev.data.reject_decision,
          });
          updateMessage(assistantId, (msg) => ({
            ...msg,
            streaming: false,
            activity: [...msg.activity, ev.data.message],
          }));
          setStreaming(false);
          break;
        } else if (ev.event === "error") {
          updateMessage(assistantId, (msg) => ({
            ...msg,
            content: `Erro: ${ev.data.error}`,
            activity: [...msg.activity, `Erro: ${ev.data.error}`],
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
  }, [appendMessages, input, setPendingApproval, setSessionId, streaming, updateMessage]);

  const handleDecision = useCallback(async (decision: "continue" | "respond_now" | "approve" | "deny") => {
    if (!pendingApproval || streaming) return;

    setPendingApproval(null);
    setStreaming(true);
    updateMessage(pendingApproval.assistantId, (msg) => ({
      ...msg,
      streaming: true,
      activity: [
        ...msg.activity,
        decision === "continue"
          ? "Usuário autorizou continuar a investigação."
          : decision === "respond_now"
            ? "Usuário pediu para responder imediatamente."
            : decision === "approve"
              ? "Usuário autorizou a ação solicitada."
              : "Usuário negou a ação solicitada.",
      ],
    }));

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      for await (const ev of streamChatDecision(pendingApproval.sessionId, decision, ctrl.signal)) {
        if (ev.event === "text") {
          updateMessage(pendingApproval.assistantId, (msg) => ({
            ...msg,
            content: msg.content + ev.data.text,
            activity: msg.activity.includes("Gerando resposta.")
              ? msg.activity
              : [...msg.activity, "Gerando resposta."],
          }));
        } else if (ev.event === "tool") {
          updateMessage(pendingApproval.assistantId, (msg) => ({
            ...msg,
            tools: [...msg.tools, ev.data.tool],
            activity: [...msg.activity, `Tool chamada: ${ev.data.tool}`],
          }));
        } else if (ev.event === "approval") {
          setPendingApproval({
            assistantId: pendingApproval.assistantId,
            sessionId: ev.data.session_id,
            message: ev.data.message,
            approveLabel: ev.data.approve_label,
            rejectLabel: ev.data.reject_label,
            approveDecision: ev.data.approve_decision,
            rejectDecision: ev.data.reject_decision,
          });
          updateMessage(pendingApproval.assistantId, (msg) => ({
            ...msg,
            streaming: false,
            activity: [...msg.activity, ev.data.message],
          }));
          setStreaming(false);
          return;
        } else if (ev.event === "error") {
          updateMessage(pendingApproval.assistantId, (msg) => ({
            ...msg,
            content: `Erro: ${ev.data.error}`,
            activity: [...msg.activity, `Erro: ${ev.data.error}`],
            streaming: false,
            error: true,
          }));
          setStreaming(false);
          return;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        updateMessage(pendingApproval.assistantId, (msg) => ({
          ...msg,
          content: "Falha na conexão.",
          streaming: false,
          error: true,
        }));
      }
    }

    updateMessage(pendingApproval.assistantId, (msg) => ({ ...msg, streaming: false }));
    setStreaming(false);
    textareaRef.current?.focus();
  }, [pendingApproval, setPendingApproval, streaming, updateMessage]);

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">

        <div className="flex-1 overflow-y-auto py-8">
          {messages.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="mx-auto max-w-2xl space-y-6 px-3 sm:px-5">
              {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <div className="border-t border-border/50 bg-surface px-3 sm:px-5 pb-3 sm:pb-5 pt-3">
          {pendingApproval && pendingApproval.sessionId === sessionId && (
            <div className="mx-auto mb-3 max-w-2xl rounded-xl border border-accent/25 bg-accent-dim/60 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Autorização</p>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-text">{pendingApproval.message}</p>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => void handleDecision(pendingApproval.approveDecision)}
                  className="inline-flex min-w-[10rem] items-center justify-center rounded-lg border border-accent bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent-h"
                >
                  {pendingApproval.approveLabel || "Autorizar"}
                </button>
                <button
                  onClick={() => void handleDecision(pendingApproval.rejectDecision)}
                  className="inline-flex min-w-[10rem] items-center justify-center rounded-lg border border-border bg-surface2 px-3 py-2 text-sm font-semibold text-text hover:border-border-2"
                >
                  {pendingApproval.rejectLabel || "Negar"}
                </button>
              </div>
            </div>
          )}
          <div className="mx-auto flex max-w-2xl items-end gap-2 sm:gap-3">
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
        className="mb-2 h-32 w-32 sm:h-52 sm:w-52 object-contain"
      />
      <h2 className="mb-1.5 text-base font-semibold text-strong">Olá, sou o Hughie</h2>
      <p className="max-w-xs text-sm leading-relaxed text-muted">
        Seu agente pessoal persistente. Tenho memória e posso acessar seus ambientes remotamente.
      </p>
    </div>
  );
}

function ActivityBlock({ activity, streaming }: { activity: string[]; streaming: boolean }) {
  const [open, setOpen] = useState(true);
  if (activity.length === 0 && !streaming) return null;

  const label = streaming
    ? <span>pensando<span className="animate-blink">…</span></span>
    : <span className="opacity-50">{activity.length} {activity.length === 1 ? "passo" : "passos"}</span>;

  return (
    <div className="text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-muted hover:text-text transition-colors py-0.5"
      >
        <span className={clsx("inline-block text-[9px] transition-transform duration-150", open && "rotate-90")}>
          ▶
        </span>
        {label}
      </button>
      {open && (
        <div className="mt-0.5 ml-2.5 border-l-2 border-border/40 pl-3 pb-1 space-y-0.5">
          {activity.map((line, i) => (
            <p key={i} className="text-[11px] text-muted/75 leading-snug font-mono">{line}</p>
          ))}
          {streaming && <p className="text-[11px] text-muted/30 animate-pulse font-mono">…</p>}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  const hasActivity = !isUser && (msg.activity.length > 0 || msg.streaming);

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
        {isUser ? "E" : <img src="/Hughie.svg" alt="Hughie" className="h-5 w-5 object-contain" />}
      </div>

      <div className={clsx("flex min-w-0 flex-col gap-1.5", isUser ? "max-w-[80%] items-end" : "flex-1")}>
        {hasActivity && (
          <ActivityBlock activity={msg.activity} streaming={msg.streaming} />
        )}

        {(msg.content || msg.error) && (
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
                {msg.content && <MarkdownContent content={msg.content} />}
                {msg.streaming && msg.content && (
                  <span className="ml-0.5 inline-block h-[0.9em] w-0.5 animate-blink rounded-sm bg-accent align-middle" />
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
