// TODO: implement memory / brain notes view
// Connects to: fetchNotes(), searchNotes() from api/client.ts
//
// Layout sketch:
//
//  ┌─────────────────────────────────────────────────┐
//  │  [search input]                 [filter: type]  │
//  │  ──────────────────────────────────────────────  │
//  │  [note card: title / type badge / content]      │
//  │  [note card: title / type badge / content]      │
//  │  ...                                            │
//  └─────────────────────────────────────────────────┘

export default function MemoryPage() {
  return (
    <div className="flex h-full items-center justify-center text-muted text-sm">
      <div className="text-center space-y-2">
        <div className="text-4xl">🧠</div>
        <p className="text-[#e8e8e8] font-medium">Memória</p>
        <p>Brain notes em construção</p>
      </div>
    </div>
  );
}
