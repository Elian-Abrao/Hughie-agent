import { NavLink, Routes, Route } from "react-router-dom";
import { clsx } from "clsx";
import ChatPage from "./pages/ChatPage";
import MemoryPage from "./pages/MemoryPage";

const NAV_ITEMS = [
  { to: "/", label: "Chat", exact: true },
  { to: "/memory", label: "Memória", exact: false },
];

export default function App() {
  return (
    <div className="flex h-full bg-bg text-[#e8e8e8] overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className="w-52 flex-shrink-0 border-r border-border bg-surface flex flex-col">
        {/* Logo */}
        <div className="h-13 flex items-center px-4 border-b border-border">
          <span className="text-accent font-bold text-lg tracking-tight">Hughie</span>
        </div>

        {/* Navigation */}
        <nav className="flex flex-col gap-0.5 p-2 pt-3">
          {NAV_ITEMS.map(({ to, label, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) =>
                clsx(
                  "px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-accent-dim text-accent"
                    : "text-muted hover:text-[#e8e8e8] hover:bg-surface2"
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 min-w-0 overflow-hidden">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/memory" element={<MemoryPage />} />
        </Routes>
      </main>
    </div>
  );
}
