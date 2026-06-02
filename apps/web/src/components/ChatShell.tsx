"use client";

import { FormEvent, Fragment, useState } from "react";
import { CitationsPanel } from "./CitationsPanel";

const WATCHLIST = ["AAPL", "GOOGL", "MSFT", "NVDA", "AMZN", "JPM", "UNH", "XOM", "COST"];

type Citation = {
  accession_number: string;
  date: string;
  form_type: string;
  excerpt?: string;
  source_url?: string;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Render plain text with **bold** and newline support — no extra deps. */
function MessageContent({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, li) => (
        <Fragment key={li}>
          {li > 0 && <br />}
          {line.split(/(\*\*[^*]+\*\*)/).map((part, pi) =>
            part.startsWith("**") && part.endsWith("**") ? (
              <strong key={pi}>{part.slice(2, -2)}</strong>
            ) : (
              <span key={pi}>{part}</span>
            )
          )}
        </Fragment>
      ))}
    </>
  );
}

export function ChatShell() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Hey! Ask me anything about a stock — earnings, recent filings, price, news. I'll pull the latest data.",
    },
  ]);
  const [input, setInput] = useState("");
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);

    // Append an empty streaming assistant bubble immediately
    setMessages((m) => [...m, { role: "assistant", content: "", streaming: true }]);

    try {
      const res = await fetch(`${API_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, ticker: ticker || null, history }),
      });

      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        const detail = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
        throw new Error(detail);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6);
          if (raw === "[DONE]") {
            setLoading(false);
            break;
          }
          let event: Record<string, unknown>;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          if ("text" in event) {
            setMessages((m) => {
              const last = { ...m[m.length - 1] };
              last.content = (last.content ?? "") + (event.text as string);
              return [...m.slice(0, -1), last];
            });
          } else if ("citations" in event) {
            setMessages((m) => {
              const last = { ...m[m.length - 1], citations: event.citations as Citation[], streaming: false };
              return [...m.slice(0, -1), last];
            });
          }
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setMessages((m) => {
        // Replace the empty streaming bubble with the error
        const withoutStreaming = m.filter((x) => !(x.role === "assistant" && x.streaming));
        return [
          ...withoutStreaming,
          {
            role: "assistant",
            content:
              msg === "Failed to fetch"
                ? `Could not reach API at ${API_URL}. Start FastAPI: cd apps/api && uvicorn app.main:app --reload --reload-dir app`
                : `API error: ${msg}`,
          },
        ];
      });
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
          <div key={i} className={msg.role === "user" ? "flex justify-end" : ""}>
            <div
              className={`max-w-2xl rounded-lg px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-emerald-600 text-white"
                  : "bg-zinc-100 text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
              }`}
            >
              <MessageContent text={msg.content} />
              {msg.role === "assistant" && !msg.streaming && (
                <CitationsPanel citations={msg.citations ?? []} />
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            <span className="inline-flex gap-1">
              <span className="animate-bounce [animation-delay:0ms]">•</span>
              <span className="animate-bounce [animation-delay:150ms]">•</span>
              <span className="animate-bounce [animation-delay:300ms]">•</span>
            </span>
            Thinking…
          </div>
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
          placeholder="Ask about any stock, filing, or earnings…"
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
