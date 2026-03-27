const BASE = import.meta.env.VITE_API_URL ?? "";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BrainNote {
  id: string;
  title: string;
  type: string;
  importance: number;
  status: string;
  content: string;
  updated_at: string;
}

export interface Session {
  session_id: string;
  message_count: number;
  last_at: string;
  last_message: string;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export type StreamEvent =
  | { event: "session"; data: { session_id: string } }
  | { event: "text"; data: { text: string } }
  | { event: "tool"; data: { tool: string } }
  | { event: "error"; data: { error: string } }
  | { event: "done"; data: Record<string, never> };

// ── Chat ──────────────────────────────────────────────────────────────────────

export async function* streamChat(
  message: string,
  sessionId: string,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!;

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        eventName = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const raw = line.slice(6).trim();
        if (!raw || raw === "[DONE]") continue;
        try {
          const data = JSON.parse(raw);
          if (eventName) yield { event: eventName, data } as StreamEvent;
        } catch {
          // ignore malformed SSE
        }
        eventName = null;
      }
    }
  }
}

// ── Sessions ──────────────────────────────────────────────────────────────────

export async function fetchSessions(limit = 30): Promise<Session[]> {
  const res = await fetch(`${BASE}/v1/sessions?limit=${limit}`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchSessionMessages(sessionId: string): Promise<SessionMessage[]> {
  const res = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) return [];
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  return res.ok;
}

// ── Brain ─────────────────────────────────────────────────────────────────────

export async function fetchNote(id: string): Promise<BrainNote | null> {
  const res = await fetch(`${BASE}/v1/brain/notes/${encodeURIComponent(id)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function updateNote(
  id: string,
  payload: Pick<BrainNote, "title" | "content" | "type" | "importance" | "status">
): Promise<BrainNote | null> {
  const res = await fetch(`${BASE}/v1/brain/notes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function deleteNote(id: string): Promise<boolean> {
  const res = await fetch(`${BASE}/v1/brain/notes/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  return res.ok;
}

export async function fetchNotes(noteType = "", limit = 100): Promise<BrainNote[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (noteType) params.set("note_type", noteType);
  const res = await fetch(`${BASE}/v1/brain/notes?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function searchNotes(q: string, limit = 5): Promise<BrainNote[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  const res = await fetch(`${BASE}/v1/brain/search?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// ── Brain graph ───────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  importance: number;
  status: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export async function fetchBrainGraph(): Promise<GraphData> {
  const res = await fetch(`${BASE}/v1/brain/graph`);
  if (!res.ok) return { nodes: [], edges: [] };
  return res.json();
}
