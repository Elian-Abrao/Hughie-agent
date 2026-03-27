import { useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { fetchNotes, searchNotes } from "../api/client";
import type { BrainNote } from "../api/client";
import { IconSearch, IconX } from "../components/Icons";

const TYPES = ["", "preference", "pattern", "project", "person", "fact"] as const;

const TYPE_META: Record<string, { label: string; dot: string; badge: string }> = {
  "":          { label: "Todas",       dot: "bg-muted",       badge: "text-muted-2 bg-surface3 border-border-2" },
  preference:  { label: "Preferência", dot: "bg-blue-400",    badge: "text-blue-300 bg-blue-950/50 border-blue-800/50" },
  pattern:     { label: "Padrão",      dot: "bg-purple-400",  badge: "text-purple-300 bg-purple-950/50 border-purple-800/50" },
  project:     { label: "Projeto",     dot: "bg-emerald-400", badge: "text-emerald-300 bg-emerald-950/50 border-emerald-800/50" },
  person:      { label: "Pessoa",      dot: "bg-orange-400",  badge: "text-orange-300 bg-orange-950/50 border-orange-800/50" },
  fact:        { label: "Fato",        dot: "bg-zinc-400",    badge: "text-zinc-300 bg-zinc-800/60 border-zinc-700/50" },
  file:        { label: "Arquivo",     dot: "bg-yellow-400",  badge: "text-yellow-300 bg-yellow-950/50 border-yellow-800/50" },
  directory:   { label: "Diretório",   dot: "bg-teal-400",    badge: "text-teal-300 bg-teal-950/50 border-teal-800/50" },
};

function getMeta(type: string) {
  return TYPE_META[type] ?? TYPE_META.fact;
}

export default function MemoryPage() {
  const [notes, setNotes]           = useState<BrainNote[]>([]);
  const [query, setQuery]           = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading]       = useState(false);
  const [selected, setSelected]     = useState<BrainNote | null>(null);

  const loadAll = useCallback(async (type: string) => {
    setLoading(true);
    try { setNotes(await fetchNotes(type, 200)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (!query) loadAll(typeFilter); }, [typeFilter, query, loadAll]);

  const runSearch = useCallback(async () => {
    if (!query.trim()) { loadAll(typeFilter); return; }
    setLoading(true);
    try { setNotes(await searchNotes(query, 30)); }
    finally { setLoading(false); }
  }, [query, typeFilter, loadAll]);

  const clearSearch = () => { setQuery(""); loadAll(typeFilter); };

  const handleTypeFilter = (type: string) => { setTypeFilter(type); setQuery(""); };

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── List ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="px-6 py-4 border-b border-border bg-surface/60 backdrop-blur-sm flex-shrink-0 space-y-3">
          {/* Search */}
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runSearch(); if (e.key === "Escape") clearSearch(); }}
                placeholder="Busca semântica…"
                className="w-full bg-surface2 border border-border rounded-lg pl-9 pr-4 py-2 text-sm text-[#d8d8f0] placeholder-muted outline-none focus:border-accent focus:ring-1 focus:ring-accent/20 transition-all"
              />
              {query && (
                <button onClick={clearSearch} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-[#d8d8f0] transition-colors">
                  <IconX size={13} />
                </button>
              )}
            </div>
            <button
              onClick={runSearch}
              className="px-4 py-2 bg-accent hover:bg-accent-h text-white rounded-lg text-sm font-medium transition-colors shadow-[0_0_10px_rgba(124,106,247,0.3)]"
            >
              Buscar
            </button>
          </div>

          {/* Type pills */}
          <div className="flex flex-wrap gap-1.5">
            {TYPES.map((type) => {
              const meta = getMeta(type);
              const active = typeFilter === type && !query;
              return (
                <button
                  key={type}
                  onClick={() => handleTypeFilter(type)}
                  className={clsx(
                    "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border transition-all",
                    active ? "bg-accent text-white border-accent shadow-[0_0_8px_rgba(124,106,247,0.4)]" : "border-border text-muted hover:text-[#d8d8f0] hover:border-border-2"
                  )}
                >
                  {type && <span className={clsx("w-1.5 h-1.5 rounded-full flex-shrink-0", meta.dot)} />}
                  {meta.label}
                </button>
              );
            })}
          </div>

          <p className="text-xs text-muted">
            {loading ? "Carregando…" : `${notes.length} nota${notes.length !== 1 ? "s" : ""}${query ? " encontradas" : ""}`}
          </p>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex items-center justify-center h-40">
              <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin-slow" />
            </div>
          )}
          {!loading && notes.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-4xl mb-3">🧠</div>
              <p className="text-muted text-sm">{query ? "Nenhuma nota para essa busca" : "Nenhuma nota ainda"}</p>
            </div>
          )}
          {!loading && notes.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {notes.map((note) => (
                <NoteCard
                  key={note.id}
                  note={note}
                  selected={selected?.id === note.id}
                  onClick={() => setSelected((p) => (p?.id === note.id ? null : note))}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Detail panel ── */}
      {selected && (
        <div className="w-72 flex-shrink-0 border-l border-border bg-surface flex flex-col animate-fadein">
          <div className="flex items-center justify-between p-4 border-b border-border">
            <TypeBadge type={selected.type} />
            <button
              onClick={() => setSelected(null)}
              className="w-7 h-7 flex items-center justify-center rounded-lg text-muted hover:text-[#d8d8f0] hover:bg-surface2 transition-colors"
            >
              <IconX size={14} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <h2 className="text-[#e0e0f8] font-semibold leading-snug">{selected.title}</h2>
            <p className="text-sm text-[#a8a8c8] leading-relaxed whitespace-pre-wrap">{selected.content}</p>
            <div className="pt-3 border-t border-border space-y-2 text-xs">
              <Row label="Importância" value={selected.importance.toFixed(1)} />
              <Row label="Status"      value={<span className="capitalize">{selected.status}</span>} />
              <Row label="Atualizado"  value={new Date(selected.updated_at).toLocaleDateString("pt-BR")} />
              <p className="font-mono text-[10px] break-all text-muted/60 pt-1">{selected.id}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function NoteCard({ note, selected, onClick }: { note: BrainNote; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "group text-left p-4 rounded-xl border transition-all duration-150 space-y-2.5",
        selected
          ? "border-accent bg-accent-dim shadow-[0_0_0_1px_rgba(124,106,247,0.5),0_0_20px_rgba(124,106,247,0.1)]"
          : "border-border bg-surface hover:border-border-2 hover:bg-surface2 hover:shadow-[0_4px_12px_rgba(0,0,0,0.4)]"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-[#d8d8f0] leading-snug group-hover:text-[#e8e8ff] transition-colors">
          {note.title}
        </p>
        <TypeBadge type={note.type} />
      </div>
      <p className="text-xs text-muted leading-relaxed line-clamp-3">{note.content}</p>
      {note.importance >= 1.5 && (
        <div className="flex items-center gap-1">
          <span className="text-yellow-400 text-xs">★</span>
          <span className="text-[11px] text-muted">{note.importance.toFixed(1)}</span>
        </div>
      )}
    </button>
  );
}

function TypeBadge({ type }: { type: string }) {
  const meta = getMeta(type);
  return (
    <span className={clsx("flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border flex-shrink-0", meta.badge)}>
      <span className={clsx("w-1.5 h-1.5 rounded-full flex-shrink-0", meta.dot)} />
      {meta.label}
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted">{label}</span>
      <span className="text-[#c0c0e0]">{value}</span>
    </div>
  );
}
