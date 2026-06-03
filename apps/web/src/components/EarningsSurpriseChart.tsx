"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  LabelList,
} from "recharts";

type EarningsEntry = {
  date: string;
  eps: number | null;
  epsEstimated: number | null;
  surprisePct: number | null;
};

function quarterLabel(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const q = Math.floor(d.getMonth() / 3) + 1;
  const yr = String(d.getFullYear()).slice(2);
  return `Q${q} '${yr}`;
}

function surpriseLabel(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

export function EarningsSurpriseChart({ data }: { data: EarningsEntry[] }) {
  if (!data.length) {
    return (
      <div className="flex h-[220px] items-center justify-center text-sm text-zinc-400">
        No earnings data
      </div>
    );
  }

  const chartData = [...data].reverse().map((e) => ({
    name: quarterLabel(e.date),
    actual: e.eps,
    estimate: e.epsEstimated,
    surpriseLabel: surpriseLabel(e.surprisePct),
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} barGap={4} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis tick={{ fontSize: 12 }} width={40} />
        <Tooltip
          formatter={(val, name) => [
            typeof val === "number" ? val.toFixed(2) : "n/a",
            name === "actual" ? "Actual EPS" : "Estimated EPS",
          ]}
        />
        <ReferenceLine y={0} stroke="#71717a" strokeWidth={1} />
        <Bar dataKey="estimate" fill="#a1a1aa" radius={[3, 3, 0, 0]} name="estimate" />
        <Bar dataKey="actual" fill="#10b981" radius={[3, 3, 0, 0]} name="actual">
          <LabelList
            dataKey="surpriseLabel"
            position="top"
            style={{ fontSize: 11, fill: "#6b7280" }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
