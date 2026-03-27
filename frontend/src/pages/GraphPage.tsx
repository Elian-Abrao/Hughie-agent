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

function temporalColor(weight: number) {
  if (weight >= 0.75) return "#22c55e";
  if (weight >= 0.4) return "#f59e0b";
  return "#ef4444";
}

export default function GraphPage() {
  const containerRef  = useRef<HTMLDivElement>(null);
  const graphRef      = useRef<any>(null);
  const [graphData, setGraphData]     = useState<GraphData | null>(null);
  const [selected, setSelected]       = useState<GraphNode | null>(null);
  const [noteDetail, setNoteDetail]   = useState<BrainNote | null>(null);
  const [loadingNote, setLoadingNote] = useState(false);
  const [loading, setLoading]         = useState(true);
  const [typeFilter, setTypeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);

  const filteredNodes = (graphData?.nodes ?? []).filter((node) => {
    if (typeFilter && node.type !== typeFilter) return false;
    if (sourceFilter && node.fonte !== sourceFilter) return false;
    if ((node.confianca ?? 0) < minConfidence) return false;
    return true;
  });
  const allowedNodeIds = new Set(filteredNodes.map((node) => node.id));
  const filteredEdges = (graphData?.edges ?? []).filter(
    (edge) => allowedNodeIds.has(edge.source) && allowedNodeIds.has(edge.target),
  );
  const filteredGraphData = { nodes: filteredNodes, edges: filteredEdges };
  const availableTypes = Array.from(new Set((graphData?.nodes ?? []).map((node) => node.type))).sort();
  const availableSources = Array.from(new Set((graphData?.nodes ?? []).map((node) => node.fonte))).sort();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBrainGraph();
      setGraphData(data);
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
    if (!containerRef.current || !filteredGraphData || filteredGraphData.nodes.length === 0) return;

    const el = containerRef.current;

    import("force-graph").then((mod) => {
      if (!el) return;
      const ForceGraph = (mod as any).default ?? mod;

      const nodes = filteredGraphData.nodes.map((n) => ({ ...n }));
      const links = filteredGraphData.edges.map((e) => ({ ...e }));

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
          const ring = temporalColor(node.peso_temporal ?? 0);
          const alpha = Math.max(0.25, Math.min(1, node.confianca ?? 0.3));

          const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 2.5);
          grad.addColorStop(0, color + "30");
          grad.addColorStop(1, "transparent");
          ctx.beginPath();
          ctx.arc(node.x, node.y, r * 2.5, 0, Math.PI * 2);
          ctx.fillStyle = grad;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.globalAlpha = alpha;
          ctx.fillStyle = color;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.strokeStyle = ring;
          ctx.lineWidth = 2;
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
        .linkColor((link: any) => link.fonte === "execucao_real" ? "rgba(34,197,94,0.35)" : "rgba(148,163,184,0.18)")
        .linkWidth((link: any) => Math.max(1, (link.confianca ?? 0.3) * 3))
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
  }, [filteredGraphData]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b dark:border-white/[0.08] border-black/[0.08]">
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="rounded-lg bg-surface px-3 py-2 text-sm">
          <option value="">Todos os tipos</option>
          {availableTypes.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} className="rounded-lg bg-surface px-3 py-2 text-sm">
          <option value="">Todas as fontes</option>
          {availableSources.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-muted">
          <span>Confiança mínima</span>
          <input type="range" min={0} max={1} step={0.1} value={minConfidence} onChange={(e) => setMinConfidence(Number(e.target.value))} />
          <span>{minConfidence.toFixed(1)}</span>
        </label>
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
          <div className="absolute top-4 right-4 w-72 max-h-[calc(100%-2rem)] flex flex-col bg-surface dark:bg-[#0f0f18]/95 backdrop-blur-md border dark:border-white/[0.1] border-black/[0.12] rounded-xl shadow-2xl animate-fadein overflow-hidden">
            <div className="flex items-start justify-between gap-2 px-4 pt-4 pb-3 border-b dark:border-white/[0.07] border-black/[0.08] shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: typeColor(selected.type) }} />
                <h3 className="text-sm font-semibold text-strong leading-snug">{selected.label}</h3>
              </div>
              <button onClick={() => setSelected(null)} className="shrink-0 text-muted hover:text-text transition-colors mt-0.5">
                <IconX size={14} />
              </button>
            </div>

            <div className="flex items-center gap-2 px-4 py-2 shrink-0 text-xs text-muted">
              <span className="capitalize">{selected.type}</span>
              <span className="opacity-30">·</span>
              <span>★ {(selected.importance ?? 1).toFixed(1)}</span>
              <span className="opacity-30">·</span>
              <span>{selected.fonte}</span>
              <span className="opacity-30">·</span>
              <span>conf {(selected.confianca ?? 0).toFixed(2)}</span>
              <span className="opacity-30">·</span>
              <span style={{ color: temporalColor(selected.peso_temporal ?? 0) }}>
                tempo {(selected.peso_temporal ?? 0).toFixed(2)}
              </span>
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
                <div className="prose-chat text-[12px] leading-relaxed text-muted">
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
