import { create } from "zustand";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: string[];
  streaming: boolean;
  error: boolean;
}

interface ChatStore {
  sessionId: string;
  messages: Message[];
  setSessionId: (id: string) => void;
  setMessages: (msgs: Message[]) => void;
  appendMessages: (msgs: Message[]) => void;
  updateMessage: (id: string, updater: (m: Message) => Message) => void;
  reset: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  sessionId: "",
  messages: [],

  setSessionId: (id) => set({ sessionId: id }),

  setMessages: (messages) => set({ messages }),

  appendMessages: (msgs) =>
    set((s) => ({ messages: [...s.messages, ...msgs] })),

  updateMessage: (id, updater) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? updater(m) : m)),
    })),

  reset: () => set({ sessionId: "", messages: [] }),
}));
