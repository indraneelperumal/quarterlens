"use client";

type CalendarItem = {
  symbol: string;
  date: string;
  epsEstimated: number | null;
  time: string;
};

function timeLabel(t: string): string {
  if (t === "bmo") return "Before Open";
  if (t === "amc") return "After Close";
  return t;
}

export function EarningsCalendar({ items }: { items: CalendarItem[] }) {
  if (!items.length) {
    return (
      <p className="text-sm text-zinc-400">No upcoming earnings in the next 7 days</p>
    );
  }

  return (
    <ul className="space-y-2">
      {items.slice(0, 10).map((item, i) => (
        <li
          key={i}
          className="flex items-center justify-between rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700"
        >
          <span className="w-16 font-semibold text-zinc-900 dark:text-zinc-100">
            {item.symbol}
          </span>
          <span className="flex-1 text-zinc-600 dark:text-zinc-400">{item.date}</span>
          <span className="text-xs text-zinc-500">{timeLabel(item.time)}</span>
          {item.epsEstimated != null && (
            <span className="ml-4 w-20 text-right text-zinc-700 dark:text-zinc-300">
              est. ${item.epsEstimated.toFixed(2)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
