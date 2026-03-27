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
  { to: "/",       label: "Chat",    Icon: IconChat,  exact: true  },
  { to: "/memory", label: "Memória", Icon: IconBrain, exact: false },
  { to: "/graph",  label: "Grafo",   Icon: IconGraph, exact: false },
];

export default function App() {
  const location  = useLocation();
  const navigate  = useNavigate();
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
      {/* ── Sidebar ── */}
      <aside
        className={clsx(
          "relative flex shrink-0 flex-col border-r border-white/[0.07] bg-surface/70 backdrop-blur-md",
          "transition-all duration-200 ease-in-out",
          collapsed ? "w-[56px]" : "w-[240px]"
        )}
      >
        {/* Logo row */}
        <div className={clsx(
          "flex h-14 shrink-0 items-center gap-2.5 overflow-hidden border-b border-white/[0.06]",
          collapsed ? "justify-center px-0" : "px-4"
        )}>
          <img src="/Hughie.svg" alt="Hughie" className="h-7 w-7 shrink-0 object-contain" />
          {!collapsed && (
            <span className="whitespace-nowrap text-[13px] font-semibold text-[#e0e0f0] tracking-tight">
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
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-white/[0.06] hover:text-text transition-colors"
            >
              <IconPlus size={15} />
            </button>
          ) : (
            <button
              onClick={newSession}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-muted hover:bg-white/[0.06] hover:text-text transition-colors"
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
                    ? "bg-white/[0.09] text-[#e0e0f8]"
                    : "text-muted hover:bg-white/[0.05] hover:text-[#c0c0e0]"
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
                    <button
                      key={s.session_id}
                      onClick={() => openSession(s.session_id)}
                      className={clsx(
                        "w-full rounded-lg px-3 py-2 text-left transition-colors",
                        active
                          ? "bg-white/[0.09] text-[#d8d8f0]"
                          : "text-muted hover:bg-white/[0.05] hover:text-[#b8b8d8]"
                      )}
                    >
                      <div className="flex items-center justify-between gap-1 mb-0.5">
                        <span className="truncate font-mono text-[11px] opacity-60">
                          {s.session_id.slice(0, 10)}
                        </span>
                        <span className="shrink-0 text-[10px] opacity-40">{reltime(s.last_at)}</span>
                      </div>
                      <p className="truncate text-[11px] leading-snug opacity-70">
                        {s.last_message}
                      </p>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Bottom actions */}
        <div className={clsx(
          "mt-auto shrink-0 border-t border-white/[0.06] px-2 py-2 flex flex-col gap-0.5",
          collapsed && "items-center"
        )}>
          <button
            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
            title={theme === "dark" ? "Tema claro" : "Tema escuro"}
            className={clsx(
              "flex items-center gap-2.5 rounded-lg text-[13px] text-muted hover:bg-white/[0.05] hover:text-[#c0c0e0] transition-colors",
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
              "flex items-center gap-2.5 rounded-lg text-[13px] text-muted hover:bg-white/[0.05] hover:text-[#c0c0e0] transition-colors",
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

      {/* ── Main ── */}
      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/"       element={<ChatPage />}   />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/graph"  element={<GraphPage />}  />
        </Routes>
      </main>
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
