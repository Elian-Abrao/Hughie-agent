/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { fetchBrainGraph, fetchNote } from "../api/client";
import type { GraphData, GraphNode, BrainNote } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";
import { IconX } from "../components/Icons";

const TYPE_COLOR: Record<string, string> = {
  preference: "#7dd3fc",
  pattern:    "#c4b5fd",
  project:    "#6ee7b7",
  person:     "#fda4af",
  fact:       "#94a3b8",
  file:       "#fde68a",
  directory:  "#5eead4",
};

function typeColor(type: string) {
  return TYPE_COLOR[type] ?? "#94a3b8";
}

export default function GraphPage() {
  const containerRef  = useRef<HTMLDivElement>(null);
  const graphRef      = useRef<any>(null);
  const [graphData, setGraphData]     = useState<GraphData | null>(null);
  const [selected, setSelected]       = useState<GraphNode | null>(null);
  const [noteDetail, setNoteDetail]   = useState<BrainNote | null>(null);
  const [loadingNote, setLoadingNote] = useState(false);
  const [loading, setLoading]         = useState(true);
  const [counts, setCounts]           = useState({ nodes: 0, edges: 0 });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBrainGraph();
      setGraphData(data);
      setCounts({ nodes: data.nodes.length, edges: data.edges.length });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Fetch note detail on node click
  useEffect(() => {
    if (!selected) { setNoteDetail(null); return; }
    if (selected.id.startsWith("path:")) { setNoteDetail(null); return; }
    setLoadingNote(true);
    fetchNote(selected.id)
      .then(setNoteDetail)
      .finally(() => setLoadingNote(false));
  }, [selected]);

  useEffect(() => {
    if (!containerRef.current || !graphData || graphData.nodes.length === 0) return;

    const el = containerRef.current;

    import("force-graph").then((mod) => {
      if (!el) return;
      const ForceGraph = (mod as any).default ?? mod;

      const nodes = graphData.nodes.map((n) => ({ ...n }));
      const links = graphData.edges.map((e) => ({ ...e }));

      const fg = ForceGraph()(el)
        .width(el.offsetWidth)
        .height(el.offsetHeight)
        .backgroundColor("rgba(0,0,0,0)")
        .graphData({ nodes, links })
        .nodeCanvasObject((node: any, ctx: any) => {
          if (!isFinite(node.x) || !isFinite(node.y)) return;
          const r = Math.sqrt(Math.max(0.5, node.importance ?? 1)) * 5 + 4;
          node.__r = r;
          const color = typeColor(node.type);

          const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 2.5);
          grad.addColorStop(0, color + "30");
          grad.addColorStop(1, "transparent");
          ctx.beginPath();
          ctx.arc(node.x, node.y, r * 2.5, 0, Math.PI * 2);
          ctx.fillStyle = grad;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,0.15)";
          ctx.lineWidth = 1;
          ctx.stroke();
        })
        .nodeCanvasObjectMode(() => "replace")
        .nodePointerAreaPaint((node: any, color: string, ctx: any) => {
          ctx.beginPath();
          ctx.arc(node.x, node.y, (node.__r ?? 6) + 3, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
        })
        .nodeLabel((node: any) => node.label)
        .linkColor(() => "rgba(148,163,184,0.18)")
        .linkWidth(1)
        .linkDirectionalArrowLength(4)
        .linkDirectionalArrowColor(() => "rgba(148,163,184,0.4)")
        .linkDirectionalArrowRelPos(1)
        .onNodeClick((node: any) => {
          setSelected((prev) => (prev?.id === node.id ? null : (node as GraphNode)));
        })
        .onBackgroundClick(() => setSelected(null));

      fg.d3Force("charge")?.strength?.(-140);
      graphRef.current = fg;
    });

    return () => {
      try { graphRef.current?._destructor?.(); } catch {}
      el.innerHTML = "";
      graphRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-white/[0.07] flex-shrink-0 bg-surface/50 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-[#d8d8f0]">Grafo de memória</span>
          {!loading && (
            <span className="text-xs text-muted">
              {counts.nodes} nó{counts.nodes !== 1 ? "s" : ""} · {counts.edges} lig{counts.edges !== 1 ? "ações" : "ação"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-3">
            {Object.entries(TYPE_COLOR).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                <span className="text-[11px] text-muted capitalize">{type}</span>
              </div>
            ))}
          </div>
          <button
            onClick={load}
            className="text-xs text-muted hover:text-[#d8d8f0] transition-colors px-2 py-1 rounded-md hover:bg-white/[0.06]"
          >
            Atualizar
          </button>
        </div>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative overflow-hidden">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            <div className="flex flex-col items-center gap-3">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin-slow" />
              <span className="text-xs text-muted">Carregando grafo…</span>
            </div>
          </div>
        )}

        {!loading && graphData?.nodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
            <div className="text-4xl mb-3">🕸️</div>
            <p className="text-muted text-sm">Nenhuma nota com conexões ainda</p>
          </div>
        )}

        <div ref={containerRef} className="w-full h-full" />

        {/* Node detail panel */}
        {selected && (
          <div className="absolute top-4 right-4 w-72 max-h-[calc(100%-2rem)] flex flex-col bg-[#0f0f18]/95 backdrop-blur-md border border-white/[0.1] rounded-xl shadow-2xl animate-fadein overflow-hidden">
            <div className="flex items-start justify-between gap-2 px-4 pt-4 pb-3 border-b border-white/[0.07] shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: typeColor(selected.type) }} />
                <h3 className="text-sm font-semibold text-[#e0e0ff] leading-snug">{selected.label}</h3>
              </div>
              <button onClick={() => setSelected(null)} className="shrink-0 text-muted hover:text-[#d8d8f0] transition-colors mt-0.5">
                <IconX size={14} />
              </button>
            </div>

            <div className="flex items-center gap-2 px-4 py-2 shrink-0 text-xs text-muted">
              <span className="capitalize">{selected.type}</span>
              <span className="opacity-30">·</span>
              <span>★ {(selected.importance ?? 1).toFixed(1)}</span>
              <span className="opacity-30">·</span>
              <span className={clsx("capitalize", selected.status === "active" ? "text-emerald-400" : "")}>
                {selected.status}
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-4 pb-4 min-h-0">
              {loadingNote ? (
                <div className="flex items-center gap-2 py-3">
                  <div className="w-3.5 h-3.5 border border-accent border-t-transparent rounded-full animate-spin-slow" />
                  <span className="text-xs text-muted">Carregando…</span>
                </div>
              ) : noteDetail ? (
                <div className="prose-chat text-[12px] leading-relaxed text-[#b8b8d8]">
                  <MarkdownContent content={noteDetail.content} />
                </div>
              ) : selected.id.startsWith("path:") ? (
                <p className="text-xs text-muted pt-1 break-all font-mono">
                  {selected.id.replace("path:", "")}
                </p>
              ) : null}
            </div>
          </div>
        )}

        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-[11px] text-muted/30 pointer-events-none select-none">
          arraste · scroll para zoom · clique num nó para detalhes
        </div>
      </div>
    </div>
  );
}
