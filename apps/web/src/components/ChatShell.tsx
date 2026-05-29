"use client";

import { FormEvent, useState } from "react";

const WATCHLIST = ["AAPL", "GOOGL", "MSFT", "NVDA", "AMZN", "JPM", "UNH", "XOM", "COST"];

type Message = { role: "user" | "assistant"; content: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function ChatShell() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Earnings Intelligence Agent (MVP C). Ask about filings, guidance vs results, or recent material events. Phase 3 will connect live MCP + RAG.",
    },
  ]);
  const [input, setInput] = useState("");
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, ticker: ticker || null }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const data = (await res.json()) as { reply: string };
      setMessages((m) => [...m, { role: "assistant", content: data.reply }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content:
            msg === "Failed to fetch"
              ? `Could not reach API at ${API_URL}. Start FastAPI: cd apps/api && uvicorn app.main:app --reload --reload-dir app`
              : `API error: ${msg}. Use POST ${API_URL}/chat (not GET /). Health check: ${API_URL}/health`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
          Earnings Intelligence
        </h1>
        <label className="ml-auto flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          Ticker
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            <option value="">Auto-detect</option>
            {WATCHLIST.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`max-w-2xl rounded-lg px-4 py-3 text-sm leading-relaxed ${
              msg.role === "user"
                ? "ml-auto bg-emerald-600 text-white"
                : "bg-zinc-100 text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
            }`}
          >
            {msg.content}
          </div>
        ))}
        {loading && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Thinking…</p>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="flex gap-2 border-t border-zinc-200 p-4 dark:border-zinc-800"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Did Apple file a material 8-K recently?"
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
