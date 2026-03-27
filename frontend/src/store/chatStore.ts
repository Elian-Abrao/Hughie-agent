import { create } from "zustand";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: string[];
  activity: string[];
  streaming: boolean;
  error: boolean;
}

export interface PendingApproval {
  assistantId: string;
  sessionId: string;
  message: string;
  continueLabel: string;
  respondNowLabel: string;
}

interface ChatStore {
  sessionId: string;
  messages: Message[];
  pendingApproval: PendingApproval | null;
  setSessionId: (id: string) => void;
  setMessages: (msgs: Message[]) => void;
  appendMessages: (msgs: Message[]) => void;
  updateMessage: (id: string, updater: (m: Message) => Message) => void;
  setPendingApproval: (approval: PendingApproval | null) => void;
  reset: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  sessionId: "",
  messages: [],
  pendingApproval: null,

  setSessionId: (id) => set({ sessionId: id }),

  setMessages: (messages) => set({ messages }),

  appendMessages: (msgs) =>
    set((s) => ({ messages: [...s.messages, ...msgs] })),

  updateMessage: (id, updater) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? updater(m) : m)),
    })),

  setPendingApproval: (pendingApproval) => set({ pendingApproval }),

  reset: () => set({ sessionId: "", messages: [], pendingApproval: null }),
}));
