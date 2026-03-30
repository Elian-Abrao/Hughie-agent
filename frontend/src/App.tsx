import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import {
  IconBrain,
  IconChat,
  IconChevron,
  IconGraph,
  IconMenu,
  IconMoon,
  IconPlus,
  IconSun,
  IconTrash,
  IconX,
} from "./components/Icons";
import { deleteSession, fetchSessionMessages, fetchSessions } from "./api/client";
import type { Session } from "./api/client";
import ChatPage from "./pages/ChatPage";
import GraphPage from "./pages/GraphPage";
import MemoryPage from "./pages/MemoryPage";
import { useChatStore } from "./store/chatStore";

const NAV = [
  { to: "/",       label: "Chat",    Icon: IconChat,  exact: true  },
  { to: "/memory", label: "Memória", Icon: IconBrain, exact: false },
  { to: "/graph",  label: "Grafo",   Icon: IconGraph, exact: false },
];

export default function App() {
  const location  = useLocation();
  const navigate  = useNavigate();
  const { sessionId, setMessages, setSessionId, setPendingApproval, reset } = useChatStore();

  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true"
  );
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("theme") as "dark" | "light") || "dark"
  );
  const [sessions, setSessions] = useState<Session[]>([]);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);

  const loadSessions = useCallback(async () => {
    setSessions(await fetchSessions());
  }, []);

  useEffect(() => {
    localStorage.setItem("theme", theme);
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    void loadSessions();
    const refresh = () => { void loadSessions(); };
    window.addEventListener("hughie:sessions-refresh", refresh);
    return () => window.removeEventListener("hughie:sessions-refresh", refresh);
  }, [loadSessions]);

  const toggleSidebar = () =>
    setCollapsed((v) => {
      const next = !v;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });

  const openSession = useCallback(async (id: string) => {
    navigate("/");
    setSessionId(id);
    const turns = await fetchSessionMessages(id);
    setMessages(
      turns.map((t, i) => ({
        id: `${t.created_at}-${i}`,
        role: t.role,
        content: t.content,
        tools: [],
        activity: [],
        streaming: false,
        error: false,
      }))
    );
    setPendingApproval(null);
  }, [navigate, setMessages, setPendingApproval, setSessionId]);

  const newSession = useCallback(() => {
    navigate("/");
    reset();
    window.dispatchEvent(new Event("hughie:sessions-refresh"));
  }, [navigate, reset]);

  const removeSession = useCallback(async (id: string) => {
    const ok = window.confirm("Excluir esta conversa? Essa ação não pode ser desfeita.");
    if (!ok) return;
    const deleted = await deleteSession(id);
    if (!deleted) return;
    if (id === sessionId) {
      navigate("/");
      reset();
    }
    void loadSessions();
  }, [loadSessions, navigate, reset, sessionId]);

  return (
    <div className="flex h-full overflow-hidden text-text">

      {/* ── Desktop Sidebar ── */}
      <aside
        className={clsx(
          "hidden sm:flex flex-col relative shrink-0 border-r dark:border-white/[0.07] border-black/[0.09] bg-surface/70 backdrop-blur-md",
          "transition-all duration-200 ease-in-out",
          collapsed ? "w-[56px]" : "w-[240px]"
        )}
      >
        {/* Logo row */}
        <div className={clsx(
          "flex h-14 shrink-0 items-center gap-2.5 overflow-hidden border-b dark:border-white/[0.06] border-black/[0.08]",
          collapsed ? "justify-center px-0" : "px-4"
        )}>
          <div className="h-7 w-7 shrink-0 flex items-center justify-center rounded-lg bg-accent-dim border border-accent/30">
            <img src="/Hughie.svg" alt="Hughie" className="h-5 w-5 object-contain" />
          </div>
          {!collapsed && (
            <span className="whitespace-nowrap text-[13px] font-semibold text-strong tracking-tight">
              Hughie
            </span>
          )}
        </div>

        {/* New chat */}
        <div className={clsx("px-2 pt-3", collapsed && "flex justify-center")}>
          {collapsed ? (
            <button
              onClick={newSession}
              title="Nova sessão"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted dark:hover:bg-white/[0.06] hover:bg-black/[0.05] hover:text-text transition-colors"
            >
              <IconPlus size={15} />
            </button>
          ) : (
            <button
              onClick={newSession}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-muted dark:hover:bg-white/[0.06] hover:bg-black/[0.05] hover:text-text transition-colors"
            >
              <IconPlus size={14} />
              <span>Nova sessão</span>
            </button>
          )}
        </div>

        {/* Nav */}
        <nav className="flex flex-col gap-0.5 px-2 pt-1">
          {NAV.map(({ to, label, Icon, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 overflow-hidden rounded-lg text-[13px] transition-colors",
                  collapsed ? "mx-auto h-9 w-9 justify-center" : "px-3 py-2",
                  isActive
                    ? "dark:bg-white/[0.09] bg-black/[0.07] text-strong"
                    : "text-muted dark:hover:bg-white/[0.05] hover:bg-black/[0.04] hover:text-muted-2"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={15} className={clsx("shrink-0", isActive && "text-accent")} />
                  {!collapsed && <span className="whitespace-nowrap">{label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Sessions list */}
        {!collapsed && (
          <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden px-2">
            <p className="mb-1.5 px-3 text-[10px] font-medium uppercase tracking-widest text-muted/60">
              Recentes
            </p>
            <div className="flex-1 overflow-y-auto space-y-0.5">
              {sessions.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted/50">Sem histórico</p>
              ) : (
                sessions.map((s) => {
                  const active = s.session_id === sessionId && location.pathname === "/";
                  return (
                    <div
                      key={s.session_id}
                      className={clsx(
                        "group flex items-start gap-1 rounded-lg transition-colors",
                        active
                          ? "dark:bg-white/[0.09] bg-black/[0.07] text-text"
                          : "text-muted dark:hover:bg-white/[0.05] hover:bg-black/[0.04] hover:text-muted-2"
                      )}
                    >
                      <button
                        onClick={() => openSession(s.session_id)}
                        className="min-w-0 flex-1 px-3 py-2 text-left"
                      >
                        <div className="mb-0.5 flex items-center justify-between gap-2">
                          <div className="min-w-0 flex items-center gap-1">
                            <span className="truncate font-mono text-[11px] opacity-60">
                              {s.session_id.slice(0, 10)}
                            </span>
                            <span className="shrink-0 text-[10px] opacity-40">{reltime(s.last_at)}</span>
                          </div>
                        </div>
                        <p className="truncate text-[11px] leading-snug opacity-70">
                          {s.last_message}
                        </p>
                      </button>
                      <button
                        type="button"
                        title="Excluir conversa"
                        onClick={() => void removeSession(s.session_id)}
                        className="mr-2 mt-2 flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted transition hover:border-red-400 hover:text-red-500 dark:hover:bg-white/[0.04]"
                      >
                        <IconTrash size={12} />
                        <span>Excluir</span>
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Bottom actions */}
        <div className={clsx(
          "mt-auto shrink-0 border-t dark:border-white/[0.06] border-black/[0.08] px-2 py-2 flex flex-col gap-0.5",
          collapsed && "items-center"
        )}>
          <button
            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
            title={theme === "dark" ? "Tema claro" : "Tema escuro"}
            className={clsx(
              "flex items-center gap-2.5 rounded-lg text-[13px] text-muted dark:hover:bg-white/[0.05] hover:bg-black/[0.04] hover:text-muted-2 transition-colors",
              collapsed ? "h-9 w-9 justify-center" : "w-full px-3 py-2"
            )}
          >
            {theme === "dark" ? <IconSun size={14} /> : <IconMoon size={14} />}
            {!collapsed && <span>{theme === "dark" ? "Tema claro" : "Tema escuro"}</span>}
          </button>
          <button
            onClick={toggleSidebar}
            title={collapsed ? "Expandir" : "Recolher"}
            className={clsx(
              "flex items-center gap-2.5 rounded-lg text-[13px] text-muted dark:hover:bg-white/[0.05] hover:bg-black/[0.04] hover:text-muted-2 transition-colors",
              collapsed ? "h-9 w-9 justify-center" : "w-full px-3 py-2"
            )}
          >
            <IconChevron
              size={13}
              className={clsx("shrink-0 transition-transform duration-200", collapsed && "rotate-180")}
            />
            {!collapsed && <span>Recolher</span>}
          </button>
        </div>
      </aside>

      {/* ── Main + spacer wrapper ── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <main className="min-h-0 flex-1 overflow-hidden">
          <Routes>
            <Route path="/"       element={<ChatPage />}   />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/graph"  element={<GraphPage />}  />
          </Routes>
        </main>
        {/* Reserve space for the fixed mobile bottom nav bar */}
        <div
          className="shrink-0 sm:hidden"
          style={{ height: "calc(3.5rem + env(safe-area-inset-bottom, 0px))" }}
        />
      </div>

      {/* ── Mobile sessions drawer ── */}
      {mobileSessionsOpen && (
        <div className="fixed inset-0 z-50 flex flex-col sm:hidden animate-fadein"
             style={{ background: "rgb(var(--surface))" }}>
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
            <span className="text-sm font-semibold text-strong">Sessões</span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:text-text transition-colors"
              >
                {theme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />}
              </button>
              <button
                onClick={() => setMobileSessionsOpen(false)}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:text-text transition-colors"
              >
                <IconX size={16} />
              </button>
            </div>
          </div>

          <div className="px-4 py-3 border-b border-border shrink-0">
            <button
              onClick={() => { newSession(); setMobileSessionsOpen(false); }}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-h transition-colors"
            >
              <IconPlus size={15} />
              Nova sessão
            </button>
          </div>

          <div className="flex-1 overflow-y-auto py-2 px-3 space-y-0.5">
            {sessions.length === 0 ? (
              <p className="py-8 text-sm text-muted text-center">Sem histórico ainda</p>
            ) : (
              sessions.map((s) => {
                const active = s.session_id === sessionId && location.pathname === "/";
                return (
                  <div
                    key={s.session_id}
                    className={clsx(
                      "group flex items-start gap-1 rounded-xl transition-colors",
                      active ? "bg-accent-dim" : "hover:bg-surface2"
                    )}
                  >
                    <button
                      onClick={() => { openSession(s.session_id); setMobileSessionsOpen(false); }}
                      className="min-w-0 flex-1 px-3 py-3 text-left"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono text-xs text-muted/70">{s.session_id.slice(0, 10)}</span>
                        <span className="text-[11px] text-muted/50">{reltime(s.last_at)}</span>
                      </div>
                      <p className="truncate text-sm text-text leading-snug">{s.last_message}</p>
                    </button>
                    <button
                      onClick={() => void removeSession(s.session_id)}
                      className="mr-2 mt-3 shrink-0 rounded-lg p-2 text-muted hover:text-red-400 hover:bg-surface3 transition-colors"
                    >
                      <IconTrash size={15} />
                    </button>
                  </div>
                );
              })
            )}
          </div>

          {/* Safe area bottom spacer inside drawer */}
          <div style={{ height: "calc(3.5rem + env(safe-area-inset-bottom, 0px))" }} className="shrink-0" />
        </div>
      )}

      {/* ── Mobile bottom tab bar ── */}
      <nav
        className="fixed bottom-0 inset-x-0 sm:hidden z-40 border-t border-border bg-surface/95 backdrop-blur-md flex items-center justify-around"
        style={{ height: "calc(3.5rem + env(safe-area-inset-bottom, 0px))", paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        {NAV.map(({ to, label, Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            onClick={() => setMobileSessionsOpen(false)}
            className={({ isActive }) =>
              clsx(
                "flex flex-col items-center gap-0.5 px-5 py-1 rounded-lg text-[11px] transition-colors",
                isActive && !mobileSessionsOpen ? "text-accent" : "text-muted"
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon size={19} className={clsx(isActive && !mobileSessionsOpen && "text-accent")} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
        <button
          onClick={() => setMobileSessionsOpen(v => !v)}
          className={clsx(
            "flex flex-col items-center gap-0.5 px-5 py-1 rounded-lg text-[11px] transition-colors",
            mobileSessionsOpen ? "text-accent" : "text-muted"
          )}
        >
          <IconMenu size={19} className={clsx(mobileSessionsOpen && "text-accent")} />
          <span>Sessões</span>
        </button>
      </nav>
    </div>
  );
}

function reltime(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60_000);
  if (m < 1)  return "agora";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}
