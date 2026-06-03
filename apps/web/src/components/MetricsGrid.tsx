"use client";

type MetricsData = {
  peRatioTTM?: number | null;
  pbRatioTTM?: number | null;
  roeTTM?: number | null;
  debtToEquityTTM?: number | null;
};

function fmt(val: number | null | undefined, pct = false): string {
  if (val == null || !isFinite(val)) return "n/a";
  return pct ? `${(val * 100).toFixed(1)}%` : val.toFixed(2);
}

const METRICS: { label: string; key: keyof MetricsData; pct?: boolean }[] = [
  { label: "P/E Ratio", key: "peRatioTTM" },
  { label: "P/B Ratio", key: "pbRatioTTM" },
  { label: "ROE", key: "roeTTM", pct: true },
  { label: "Debt / Equity", key: "debtToEquityTTM" },
];

export function MetricsGrid({ metrics }: { metrics: MetricsData }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {METRICS.map(({ label, key, pct }) => (
        <div
          key={key}
          className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-700"
        >
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
          <p className="mt-1 text-xl font-semibold text-zinc-900 dark:text-zinc-100">
            {fmt(metrics[key], pct)}
          </p>
        </div>
      ))}
    </div>
  );
}
