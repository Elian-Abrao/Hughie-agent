import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import {
  IconBrain,
  IconChat,
  IconChevron,
  IconGraph,
  IconMoon,
  IconPlus,
  IconSun,
} from "./components/Icons";
import { fetchSessionMessages, fetchSessions } from "./api/client";
import type { Session } from "./api/client";
import ChatPage from "./pages/ChatPage";
import GraphPage from "./pages/GraphPage";
import MemoryPage from "./pages/MemoryPage";
import { useChatStore } from "./store/chatStore";

const NAV = [
  { to: "/", label: "Chat", Icon: IconChat, exact: true },
  { to: "/memory", label: "Memória", Icon: IconBrain, exact: false },
  { to: "/graph", label: "Grafo", Icon: IconGraph, exact: false },
];

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const { sessionId, setMessages, setSessionId, reset } = useChatStore();

  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true"
  );
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("theme") as "dark" | "light") || "dark"
  );
  const [sessions, setSessions] = useState<Session[]>([]);

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
    setCollapsed((value) => {
      const next = !value;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });

  const toggleTheme = () =>
    setTheme((value) => (value === "dark" ? "light" : "dark"));

  const openSession = useCallback(async (id: string) => {
    navigate("/");
    setSessionId(id);
    const turns = await fetchSessionMessages(id);
    setMessages(
      turns.map((turn, index) => ({
        id: `${turn.created_at}-${index}`,
        role: turn.role,
        content: turn.content,
        tools: [],
        streaming: false,
        error: false,
      }))
    );
  }, [navigate, setMessages, setSessionId]);

  const newSession = useCallback(() => {
    navigate("/");
    reset();
    window.dispatchEvent(new Event("hughie:sessions-refresh"));
  }, [navigate, reset]);

  return (
    <div className="flex h-full overflow-hidden bg-bg text-text">
      <aside
        className={clsx(
          "flex shrink-0 flex-col border-r border-border bg-gradient-to-b from-surface via-surface to-bg transition-all duration-200 ease-in-out",
          collapsed ? "w-16" : "w-[280px]"
        )}
      >
        <div
          className={clsx(
            "h-14 flex items-center border-b border-border overflow-hidden",
            collapsed ? "justify-center px-0" : "px-4"
          )}
        >
          {collapsed ? (
            <span className="text-base font-bold text-accent">H</span>
          ) : (
            <div className="min-w-0">
              <span className="block whitespace-nowrap text-base font-bold tracking-tight text-accent">
                Hughie
              </span>
              <span className="block text-[11px] leading-none text-muted">
                memória e contexto
              </span>
            </div>
          )}
        </div>

        {!collapsed && (
          <div className="px-3 pt-3">
            <button
              onClick={newSession}
              className="flex w-full items-center gap-2 rounded-xl bg-accent px-3 py-2.5 text-sm text-white shadow-[0_10px_30px_rgba(245,123,32,0.18)] transition-all hover:-translate-y-[1px] hover:bg-accent-h"
            >
              <IconPlus size={14} />
              <span>Nova sessão</span>
            </button>
          </div>
        )}

        <nav className="flex flex-col gap-1 p-2 pt-3">
          {!collapsed && (
            <span className="px-3 pb-1 text-[10px] uppercase tracking-[0.22em] text-muted">
              Navegação
            </span>
          )}
          {NAV.map(({ to, label, Icon, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 overflow-hidden rounded-xl text-sm transition-colors",
                  collapsed ? "mx-auto h-11 w-11 justify-center" : "px-3 py-2.5",
                  isActive
                    ? "bg-accent-dim text-accent"
                    : "text-muted hover:bg-surface2 hover:text-text"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={17} className={isActive ? "text-accent" : ""} />
                  {!collapsed && <span className="whitespace-nowrap">{label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {!collapsed && (
          <div className="min-h-0 flex-1 px-3 pb-3">
            <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface2/60">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <span className="text-xs uppercase tracking-[0.18em] text-muted">Sessões</span>
                <span className="text-[11px] text-muted-2">{sessions.length}</span>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                {sessions.length === 0 ? (
                  <p className="px-3 py-4 text-xs text-muted">Sem histórico ainda.</p>
                ) : (
                  sessions.map((session) => {
                    const active = session.session_id === sessionId && location.pathname === "/";
                    return (
                      <button
                        key={session.session_id}
                        onClick={() => openSession(session.session_id)}
                        className={clsx(
                          "w-full rounded-xl px-3 py-2.5 text-left transition-all",
                          active
                            ? "border border-accent/25 bg-accent-dim shadow-[inset_0_0_0_1px_rgba(245,123,32,0.08)]"
                            : "hover:bg-surface3/70"
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className={clsx("truncate font-mono text-xs", active ? "text-accent" : "text-muted-2")}>
                            {session.session_id.slice(0, 12)}
                          </span>
                          <span className="text-[10px] text-muted">{reltime(session.last_at)}</span>
                        </div>
                        <p className={clsx("mt-1 truncate text-[11px]", active ? "text-text/80" : "text-muted")}>
                          {session.last_message}
                        </p>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        )}

        <div className="space-y-1.5 border-t border-border p-2">
          <button
            onClick={toggleTheme}
            title={theme === "dark" ? "Usar tema claro" : "Usar tema escuro"}
            className={clsx(
              "flex items-center gap-3 overflow-hidden rounded-xl text-sm text-muted transition-colors hover:bg-surface2 hover:text-text",
              collapsed ? "mx-auto h-11 w-11 justify-center" : "w-full px-3 py-2.5"
            )}
          >
            {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
            {!collapsed && (
              <span className="whitespace-nowrap">
                {theme === "dark" ? "Tema claro" : "Tema escuro"}
              </span>
            )}
          </button>

          <button
            onClick={toggleSidebar}
            title={collapsed ? "Expandir" : "Colapsar"}
            className={clsx(
              "flex items-center gap-3 overflow-hidden rounded-xl text-sm text-muted transition-colors hover:bg-surface2 hover:text-text",
              collapsed ? "mx-auto h-11 w-11 justify-center" : "w-full px-3 py-2.5"
            )}
          >
            <IconChevron
              size={15}
              className={clsx("shrink-0 transition-transform duration-200", collapsed && "rotate-180")}
            />
            {!collapsed && <span className="whitespace-nowrap">Colapsar</span>}
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/graph" element={<GraphPage />} />
        </Routes>
      </main>
    </div>
  );
}

function reltime(iso: string) {
  const delta = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(delta / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
