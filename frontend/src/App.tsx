import { useState } from "react";
import { NavLink, Routes, Route } from "react-router-dom";
import { clsx } from "clsx";
import { IconChat, IconBrain, IconGraph, IconChevron } from "./components/Icons";
import ChatPage from "./pages/ChatPage";
import MemoryPage from "./pages/MemoryPage";
import GraphPage from "./pages/GraphPage";

const NAV = [
  { to: "/",       label: "Chat",    Icon: IconChat,  exact: true  },
  { to: "/memory", label: "Memória", Icon: IconBrain, exact: false },
  { to: "/graph",  label: "Grafo",   Icon: IconGraph, exact: false },
];

export default function App() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true"
  );

  const toggle = () =>
    setCollapsed((c) => {
      localStorage.setItem("sidebar-collapsed", String(!c));
      return !c;
    });

  return (
    <div className="flex h-full bg-bg text-[#d8d8f0] overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={clsx(
          "flex-shrink-0 flex flex-col border-r border-border bg-surface",
          "transition-all duration-200 ease-in-out",
          collapsed ? "w-14" : "w-[200px]"
        )}
      >
        {/* Logo */}
        <div
          className={clsx(
            "h-12 flex items-center border-b border-border flex-shrink-0 overflow-hidden",
            collapsed ? "justify-center px-0" : "px-4"
          )}
        >
          {collapsed ? (
            <span className="text-accent font-bold text-base">H</span>
          ) : (
            <span className="text-accent font-bold text-base tracking-tight whitespace-nowrap">
              Hughie
            </span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 flex flex-col gap-0.5 p-2 pt-3">
          {NAV.map(({ to, label, Icon, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg text-sm transition-colors overflow-hidden",
                  collapsed ? "justify-center h-10 w-10 mx-auto" : "px-3 py-2",
                  isActive
                    ? "bg-accent-dim text-accent"
                    : "text-muted hover:text-[#d8d8f0] hover:bg-surface2"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={17} className={isActive ? "text-accent" : ""} />
                  {!collapsed && (
                    <span className="whitespace-nowrap">{label}</span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Collapse toggle */}
        <div className="p-2 border-t border-border flex-shrink-0">
          <button
            onClick={toggle}
            title={collapsed ? "Expandir" : "Colapsar"}
            className={clsx(
              "flex items-center gap-3 rounded-lg text-sm text-muted hover:text-[#d8d8f0] hover:bg-surface2 transition-colors overflow-hidden",
              collapsed ? "justify-center h-10 w-10 mx-auto" : "w-full px-3 py-2"
            )}
          >
            <IconChevron
              size={15}
              className={clsx(
                "flex-shrink-0 transition-transform duration-200",
                collapsed ? "rotate-180" : ""
              )}
            />
            {!collapsed && <span className="whitespace-nowrap">Colapsar</span>}
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 min-w-0 overflow-hidden">
        <Routes>
          <Route path="/"       element={<ChatPage />}   />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/graph"  element={<GraphPage />}  />
        </Routes>
      </main>
    </div>
  );
}
