/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { fetchBrainGraph } from "../api/client";
import type { GraphData, GraphNode } from "../api/client";

const TYPE_COLOR: Record<string, string> = {
  preference: "#ffb36b",
  pattern: "#f97316",
  project: "#fb923c",
  person: "#facc15",
  fact: "#a8a29e",
  file: "#f59e0b",
  directory: "#ea580c",
};

function typeColor(type: string) {
  return TYPE_COLOR[type] ?? "#f97316";
}

export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef     = useRef<any>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [selected, setSelected]   = useState<GraphNode | null>(null);
  const [loading, setLoading]     = useState(true);
  const [counts, setCounts]       = useState({ nodes: 0, edges: 0 });

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
        .backgroundColor(`rgb(${getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()})`)
        .graphData({ nodes, links })
        .nodeCanvasObject((node: any, ctx: any) => {
          if (!isFinite(node.x) || !isFinite(node.y)) return;
          const r = Math.sqrt(Math.max(0.5, node.importance ?? 1)) * 5 + 4;
          node.__r = r;
          const color = typeColor(node.type);

          const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 2.5);
          grad.addColorStop(0, color + "40");
          grad.addColorStop(1, "transparent");
          ctx.beginPath();
          ctx.arc(node.x, node.y, r * 2.5, 0, Math.PI * 2);
          ctx.fillStyle = grad;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          ctx.strokeStyle = "rgba(120,100,80,0.28)";
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
        .linkColor(() => "rgba(180,110,40,0.22)")
        .linkWidth(1)
        .linkDirectionalArrowLength(4)
        .linkDirectionalArrowColor(() => "rgba(180,110,40,0.5)")
        .linkDirectionalArrowRelPos(1)
        .onNodeClick((node: any) => {
          setSelected((prev) => (prev?.id === node.id ? null : (node as GraphNode)));
        })
        .onBackgroundClick(() => setSelected(null));

      fg.d3Force("charge")?.strength?.(-120);
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
      <div className="h-12 flex items-center justify-between px-5 border-b border-border flex-shrink-0 bg-surface">
        <div className="flex items-center gap-3">
          <div>
            <span className="block text-[10px] uppercase tracking-[0.18em] text-muted">Grafo</span>
            <span className="block text-sm font-medium text-text">Conexões entre notas</span>
          </div>
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
            className="text-xs text-muted hover:text-text transition-colors px-2 py-1 rounded-md hover:bg-surface2"
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
            <p className="text-muted/60 text-xs mt-1">Converse com o Hughie para construir a memória</p>
          </div>
        )}

        <div ref={containerRef} className="w-full h-full" />

        {/* Selected node */}
        {selected && (
          <div className="absolute top-4 right-4 w-60 bg-surface border border-border rounded-xl p-4 animate-fadein">
            <div className="flex items-start justify-between gap-2 mb-3">
              <h3 className="text-sm font-semibold text-strong leading-snug">{selected.label}</h3>
              <button
                onClick={() => setSelected(null)}
                className="text-muted hover:text-text transition-colors flex-shrink-0 text-lg leading-none"
              >
                ✕
              </button>
            </div>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: typeColor(selected.type) }} />
              <span className="text-xs text-muted capitalize">{selected.type}</span>
              <span className="text-xs text-muted ml-auto">★ {(selected.importance ?? 1).toFixed(1)}</span>
            </div>
            <div className={clsx(
              "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border",
              selected.status === "active"
                ? "text-emerald-300 bg-emerald-950/50 border-emerald-800/50"
                : "text-muted bg-surface2 border-border"
            )}>
              <span className={clsx("w-1.5 h-1.5 rounded-full", selected.status === "active" ? "bg-emerald-400" : "bg-muted")} />
              {selected.status}
            </div>
          </div>
        )}

        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-[11px] text-muted/40 pointer-events-none select-none">
          arraste · scroll para zoom · clique num nó para detalhes
        </div>
      </div>
    </div>
  );
}
