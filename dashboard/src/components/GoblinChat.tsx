"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageCircle, X, Send, Trash2 } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { sendChatMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

const QUICK_QUESTIONS = [
  "How's my portfolio?",
  "Why did the AI buy BTC?",
  "What's the market outlook?",
  "Explain the last trade",
];

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-goblin-500"
          style={{
            animation: "pulse 1.2s ease-in-out infinite",
            animationDelay: `${i * 200}ms`,
          }}
        />
      ))}
    </div>
  );
}

export default function GoblinChat() {
  const { messages, isOpen, addMessage, clearHistory, toggleOpen, setOpen } = useChatStore();
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, thinking]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const handleSend = useCallback(async (text?: string) => {
    const msg = text ?? input.trim();
    if (!msg || thinking) return;
    setInput("");
    addMessage("user", msg);
    setThinking(true);

    const response = await sendChatMessage(msg);
    addMessage("assistant", response);
    setThinking(false);
  }, [input, thinking, addMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Chat bubble button */}
      {!isOpen && (
        <button
          onClick={toggleOpen}
          className="fixed bottom-6 right-6 z-50 h-12 w-12 rounded-full bg-goblin-500 shadow-lg shadow-goblin-500/20 flex items-center justify-center hover:bg-goblin-600 transition-all hover:scale-105"
        >
          <MessageCircle size={22} className="text-white" />
        </button>
      )}

      {/* Chat panel */}
      {isOpen && (
        <div className={cn(
          "fixed z-50 flex flex-col",
          // Mobile: full screen; Desktop: fixed panel
          "inset-0 sm:inset-auto sm:bottom-6 sm:right-6 sm:w-[360px] sm:h-[500px]",
          "bg-gray-900/95 backdrop-blur-xl sm:rounded-2xl border border-gray-800 shadow-2xl shadow-black/50",
          "animate-fade-in"
        )}>
          {/* Header */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 shrink-0">
            {/* Mini goblin avatar */}
            <div className="h-8 w-8 rounded-full bg-goblin-500/20 flex items-center justify-center">
              <svg width={20} height={20} viewBox="0 0 256 256">
                <ellipse cx="128" cy="140" rx="65" ry="60" fill="#7cb342" />
                <ellipse cx="102" cy="132" rx="14" ry="18" fill="#fff" />
                <ellipse cx="105" cy="134" rx="8" ry="10" fill="#2d2d2d" />
                <ellipse cx="154" cy="132" rx="14" ry="18" fill="#fff" />
                <ellipse cx="157" cy="134" rx="8" ry="10" fill="#2d2d2d" />
                <path d="M105 172 Q128 190 151 172" stroke="#2d2d2d" strokeWidth="3" fill="none" strokeLinecap="round" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="text-sm font-bold text-white">Goblin Advisor</p>
              <p className="text-[10px] text-goblin-500">AI Trading Assistant</p>
            </div>
            <button onClick={clearHistory} className="text-gray-500 hover:text-gray-300 p-1">
              <Trash2 size={14} />
            </button>
            <button onClick={() => setOpen(false)} className="text-gray-500 hover:text-white p-1">
              <X size={16} />
            </button>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
            {messages.length === 0 && !thinking && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="h-16 w-16 rounded-full bg-goblin-500/10 flex items-center justify-center mb-3">
                  <MessageCircle size={28} className="text-goblin-500" />
                </div>
                <p className="text-sm text-gray-400 mb-1">Ask me anything about your portfolio</p>
                <p className="text-[10px] text-gray-600">I have access to your positions, trades, and market data</p>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex",
                  msg.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                <div className={cn(
                  "max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed",
                  msg.role === "user"
                    ? "bg-gray-700 text-white rounded-br-sm"
                    : "bg-gray-800 text-gray-200 border border-goblin-500/20 rounded-bl-sm"
                )}>
                  {msg.content}
                </div>
              </div>
            ))}

            {thinking && (
              <div className="flex justify-start">
                <div className="bg-gray-800 rounded-xl border border-goblin-500/20 rounded-bl-sm">
                  <ThinkingDots />
                </div>
              </div>
            )}
          </div>

          {/* Quick questions */}
          {messages.length === 0 && (
            <div className="px-3 pb-2 flex flex-wrap gap-1.5 shrink-0">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className="text-[10px] px-2.5 py-1 rounded-full border border-gray-700 text-gray-400 hover:text-white hover:border-goblin-500/30 transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="px-3 pb-3 pt-1 shrink-0">
            <div className="flex items-center gap-2 bg-gray-800 rounded-xl border border-gray-700 px-3 py-2">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Goblin..."
                className="flex-1 bg-transparent text-xs text-white placeholder-gray-500 outline-none"
                disabled={thinking}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || thinking}
                className={cn(
                  "shrink-0 h-7 w-7 rounded-lg flex items-center justify-center transition-colors",
                  input.trim() && !thinking
                    ? "bg-goblin-500 text-white hover:bg-goblin-600"
                    : "bg-gray-700 text-gray-500"
                )}
              >
                <Send size={13} />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
