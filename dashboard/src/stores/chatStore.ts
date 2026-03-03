import { create } from "zustand";
import type { ChatMessage } from "@/types";

const STORAGE_KEY = "goblin-chat-history";
const MAX_MESSAGES = 100;

interface ChatState {
  messages: ChatMessage[];
  isOpen: boolean;
  addMessage: (role: "user" | "assistant", content: string) => void;
  clearHistory: () => void;
  toggleOpen: () => void;
  setOpen: (open: boolean) => void;
}

function loadMessages(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ChatMessage[]).slice(-MAX_MESSAGES) : [];
  } catch {
    return [];
  }
}

function saveMessages(messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-MAX_MESSAGES)));
  } catch {
    // ignore
  }
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: loadMessages(),
  isOpen: false,

  addMessage: (role, content) => {
    const msg: ChatMessage = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      role,
      content,
      timestamp: new Date().toISOString(),
    };
    const updated = [...get().messages, msg].slice(-MAX_MESSAGES);
    saveMessages(updated);
    set({ messages: updated });
  },

  clearHistory: () => {
    saveMessages([]);
    set({ messages: [] });
  },

  toggleOpen: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
}));
