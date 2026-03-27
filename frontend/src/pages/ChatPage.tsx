// TODO: implement full chat UI
// Connects to: streamChat(), fetchSessions(), fetchSessionMessages() from api/client.ts
//
// Layout sketch:
//
//  ┌──────────────────────┬─────────────────────────┐
//  │  Sessions list       │  Messages               │
//  │  ─────────────────── │  ───────────────────    │
//  │  [session 1]         │  [user bubble]          │
//  │  [session 2]         │  [assistant bubble]     │
//  │  [+ new session]     │   with markdown + tools │
//  │                      │                         │
//  │                      │  ─────────────────────  │
//  │                      │  [textarea] [send btn]  │
//  └──────────────────────┴─────────────────────────┘

export default function ChatPage() {
  return (
    <div className="flex h-full items-center justify-center text-muted text-sm">
      <div className="text-center space-y-2">
        <div className="text-4xl">🤖</div>
        <p className="text-[#e8e8e8] font-medium">Hughie</p>
        <p>Chat em construção</p>
      </div>
    </div>
  );
}
