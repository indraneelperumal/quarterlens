"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { EarningsSurpriseChart } from "@/components/EarningsSurpriseChart";
import { EarningsCalendar } from "@/components/EarningsCalendar";
import { MetricsGrid } from "@/components/MetricsGrid";

const WATCHLIST = ["AAPL", "GOOGL", "MSFT", "NVDA", "AMZN", "JPM", "UNH", "XOM", "COST"];
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Quote = {
  symbol: string;
  price: number;
  changesPercentage: number;
  marketCap: number;
  yearHigh: number;
  yearLow: number;
};

type EarningsEntry = {
  date: string;
  eps: number | null;
  epsEstimated: number | null;
  surprisePct: number | null;
};

type CalendarItem = {
  symbol: string;
  date: string;
  epsEstimated: number | null;
  time: string;
};

type MetricsData = {
  peRatioTTM?: number | null;
  pbRatioTTM?: number | null;
  roeTTM?: number | null;
  debtToEquityTTM?: number | null;
};

function fmtMarketCap(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "n/a";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 p-5 dark:border-zinc-700">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function DashboardPage() {
  const [ticker, setTicker] = useState("AAPL");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [earnings, setEarnings] = useState<EarningsEntry[]>([]);
  const [calendar, setCalendar] = useState<CalendarItem[]>([]);
  const [metrics, setMetrics] = useState<MetricsData>({});
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [loadingEarnings, setLoadingEarnings] = useState(false);
  const [loadingCalendar, setLoadingCalendar] = useState(false);
  const [loadingMetrics, setLoadingMetrics] = useState(false);

  useEffect(() => {
    setQuote(null);
    setEarnings([]);
    setMetrics({});

    setLoadingQuote(true);
    fetch(`${API_URL}/market/quote/${ticker}`)
      .then((r) => r.json())
      .then(setQuote)
      .catch(() => setQuote(null))
      .finally(() => setLoadingQuote(false));

    setLoadingEarnings(true);
    fetch(`${API_URL}/market/earnings/${ticker}`)
      .then((r) => r.json())
      .then(setEarnings)
      .catch(() => setEarnings([]))
      .finally(() => setLoadingEarnings(false));

    setLoadingMetrics(true);
    fetch(`${API_URL}/market/metrics/${ticker}`)
      .then((r) => r.json())
      .then(setMetrics)
      .catch(() => setMetrics({}))
      .finally(() => setLoadingMetrics(false));
  }, [ticker]);

  useEffect(() => {
    setLoadingCalendar(true);
    fetch(`${API_URL}/market/calendar`)
      .then((r) => r.json())
      .then(setCalendar)
      .catch(() => setCalendar([]))
      .finally(() => setLoadingCalendar(false));
  }, []);

  const pct = quote?.changesPercentage;
  const pctStr =
    pct == null ? "" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
  const pctColor =
    pct == null ? "" : pct >= 0 ? "text-emerald-600" : "text-red-500";

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      <header className="flex items-center gap-4">
        <Link
          href="/"
          className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
        >
          ← Chat
        </Link>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">
          Earnings Dashboard
        </h1>
        <div className="ml-auto flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          Ticker
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            {WATCHLIST.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </header>

      {/* Quote card */}
      <Section title="Quote">
        {loadingQuote ? (
          <p className="text-sm text-zinc-400">Loading…</p>
        ) : quote && quote.price ? (
          <div className="space-y-1">
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-bold text-zinc-900 dark:text-zinc-50">
                ${quote.price.toFixed(2)}
              </span>
              <span className={`text-lg font-medium ${pctColor}`}>{pctStr}</span>
              <span className="ml-auto text-sm text-zinc-500">
                Mkt cap: {fmtMarketCap(quote.marketCap)}
              </span>
            </div>
            <p className="text-sm text-zinc-500">
              52-wk: ${quote.yearLow?.toFixed(2)} – ${quote.yearHigh?.toFixed(2)}
            </p>
          </div>
        ) : (
          <p className="text-sm text-zinc-400">No quote data (FMP_API_KEY required)</p>
        )}
      </Section>

      {/* EPS chart */}
      <Section title="EPS Surprise — last 4 quarters">
        {loadingEarnings ? (
          <div className="flex h-[220px] items-center justify-center text-sm text-zinc-400">
            Loading…
          </div>
        ) : (
          <EarningsSurpriseChart data={earnings} />
        )}
      </Section>

      {/* Metrics + Calendar side by side */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Section title="Key Metrics (TTM)">
          {loadingMetrics ? (
            <p className="text-sm text-zinc-400">Loading…</p>
          ) : (
            <MetricsGrid metrics={metrics} />
          )}
        </Section>

        <Section title="Upcoming Earnings (next 7 days)">
          {loadingCalendar ? (
            <p className="text-sm text-zinc-400">Loading…</p>
          ) : (
            <EarningsCalendar items={calendar} />
          )}
        </Section>
      </div>
    </div>
  );
}
