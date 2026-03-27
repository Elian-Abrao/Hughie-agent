import { useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { deleteNote, fetchNotes, searchNotes, updateNote } from "../api/client";
import type { BrainNote } from "../api/client";
import { IconCheck, IconEdit, IconSearch, IconTrash, IconX } from "../components/Icons";

const TYPES = ["", "preference", "pattern", "project", "person", "fact"] as const;

const TYPE_META: Record<string, { label: string; dot: string; badge: string }> = {
  "":          { label: "Todas",       dot: "bg-muted",      badge: "text-muted-2 bg-surface3 border-border-2" },
  preference:  { label: "Preferência", dot: "bg-orange-300", badge: "text-accent bg-accent/10 border-accent/20" },
  pattern:     { label: "Padrão",      dot: "bg-amber-500",  badge: "text-orange-700 dark:text-orange-200 bg-orange-500/10 border-orange-500/20" },
  project:     { label: "Projeto",     dot: "bg-orange-500", badge: "text-orange-700 dark:text-orange-100 bg-orange-500/10 border-orange-500/20" },
  person:      { label: "Pessoa",      dot: "bg-yellow-500", badge: "text-yellow-700 dark:text-yellow-200 bg-yellow-500/10 border-yellow-500/20" },
  fact:        { label: "Fato",        dot: "bg-stone-400",  badge: "text-stone-700 dark:text-stone-200 bg-stone-500/10 border-stone-500/20" },
  file:        { label: "Arquivo",     dot: "bg-amber-400",  badge: "text-amber-700 dark:text-amber-200 bg-amber-500/10 border-amber-500/20" },
  directory:   { label: "Diretório",   dot: "bg-orange-600", badge: "text-orange-800 dark:text-orange-200 bg-orange-600/10 border-orange-600/20" },
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
  const [editing, setEditing]       = useState(false);
  const [saving, setSaving]         = useState(false);
  const [draft, setDraft]           = useState({
    title: "",
    content: "",
    type: "fact",
    importance: 1,
    status: "active",
  });

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

  useEffect(() => {
    if (!selected) return;
    setDraft({
      title: selected.title,
      content: selected.content,
      type: selected.type,
      importance: selected.importance,
      status: selected.status,
    });
    setEditing(false);
  }, [selected]);

  const refreshVisible = useCallback(async () => {
    if (query.trim()) {
      setNotes(await searchNotes(query, 30));
      return;
    }
    setNotes(await fetchNotes(typeFilter, 200));
  }, [query, typeFilter]);

  const handleDelete = useCallback(async () => {
    if (!selected) return;
    const ok = window.confirm("Excluir esta memória? Essa ação não pode ser desfeita.");
    if (!ok) return;
    const deleted = await deleteNote(selected.id);
    if (!deleted) return;
    setSelected(null);
    setEditing(false);
    await refreshVisible();
  }, [refreshVisible, selected]);

  const handleSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const updated = await updateNote(selected.id, draft);
      if (!updated) return;
      setSelected(updated);
      setNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }, [draft, selected]);

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── List ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="px-6 py-4 border-b border-border bg-surface flex-shrink-0 space-y-3">
          <div>
            <span className="block text-[10px] uppercase tracking-[0.18em] text-muted">Memória</span>
            <span className="block text-sm font-medium text-text">Notas persistentes do Hughie</span>
          </div>
          {/* Search */}
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runSearch(); if (e.key === "Escape") clearSearch(); }}
                placeholder="Busca semântica…"
                className="w-full bg-surface2 border border-border rounded-lg pl-9 pr-4 py-2 text-sm text-text placeholder-muted outline-none focus:border-accent transition-all"
              />
              {query && (
                <button onClick={clearSearch} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-text transition-colors">
                  <IconX size={13} />
                </button>
              )}
            </div>
            <button
              onClick={runSearch}
              className="px-4 py-2 bg-accent hover:bg-accent-h text-white rounded-lg text-sm font-medium transition-colors border border-accent"
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
                    active ? "bg-accent text-white border-accent" : "border-border text-muted hover:text-text hover:border-border-2"
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
            <div className="flex items-center gap-1">
              {editing ? (
                <button
                  onClick={() => {
                    setEditing(false);
                    setDraft({
                      title: selected.title,
                      content: selected.content,
                      type: selected.type,
                      importance: selected.importance,
                      status: selected.status,
                    });
                  }}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-surface2 hover:text-text transition-colors"
                  title="Cancelar edição"
                >
                  <IconX size={14} />
                </button>
              ) : (
                <button
                  onClick={() => setEditing(true)}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-surface2 hover:text-text transition-colors"
                  title="Editar memória"
                >
                  <IconEdit size={14} />
                </button>
              )}
              <button
                onClick={() => void handleDelete()}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-surface2 hover:text-red-500 transition-colors"
                title="Excluir memória"
              >
                <IconTrash size={14} />
              </button>
              <button
                onClick={() => setSelected(null)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:text-text hover:bg-surface2 transition-colors"
                title="Fechar"
              >
                <IconX size={14} />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {editing ? (
              <>
                <input
                  value={draft.title}
                  onChange={(e) => setDraft((prev) => ({ ...prev, title: e.target.value }))}
                  className="w-full rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text outline-none focus:border-accent"
                />
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={draft.type}
                    onChange={(e) => setDraft((prev) => ({ ...prev, type: e.target.value }))}
                    className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text outline-none focus:border-accent"
                  >
                    {TYPES.filter(Boolean).map((type) => (
                      <option key={type} value={type}>
                        {getMeta(type).label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={draft.status}
                    onChange={(e) => setDraft((prev) => ({ ...prev, status: e.target.value }))}
                    className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text outline-none focus:border-accent"
                  >
                    <option value="active">Ativa</option>
                    <option value="stub">Stub</option>
                    <option value="archived">Arquivada</option>
                  </select>
                </div>
                <label className="block text-xs text-muted">
                  Importância
                  <input
                    type="number"
                    min="0"
                    max="3"
                    step="0.1"
                    value={draft.importance}
                    onChange={(e) => setDraft((prev) => ({ ...prev, importance: Number(e.target.value) }))}
                    className="mt-1 w-full rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text outline-none focus:border-accent"
                  />
                </label>
                <textarea
                  value={draft.content}
                  onChange={(e) => setDraft((prev) => ({ ...prev, content: e.target.value }))}
                  rows={12}
                  className="w-full resize-y rounded-lg border border-border bg-surface2 px-3 py-2 text-sm leading-relaxed text-text outline-none focus:border-accent"
                />
                <button
                  onClick={() => void handleSave()}
                  disabled={saving || !draft.title.trim() || !draft.content.trim()}
                  className={clsx(
                    "flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                    saving || !draft.title.trim() || !draft.content.trim()
                      ? "cursor-not-allowed border-border bg-surface2 text-muted"
                      : "border-accent bg-accent text-white hover:bg-accent-h"
                  )}
                >
                  <IconCheck size={14} />
                  {saving ? "Salvando..." : "Salvar memória"}
                </button>
              </>
            ) : (
              <>
                <h2 className="text-strong font-semibold leading-snug">{selected.title}</h2>
                <p className="text-sm text-muted-2 leading-relaxed whitespace-pre-wrap">{selected.content}</p>
              </>
            )}
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
          ? "border-accent bg-accent-dim"
          : "border-border bg-surface hover:border-border-2 hover:bg-surface2"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-text leading-snug group-hover:text-strong transition-colors">
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
      <span className="text-muted-2">{value}</span>
    </div>
  );
}
