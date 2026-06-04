type Citation = {
  accession_number: string;
  date: string;
  form_type: string;
  excerpt?: string;
  source_url?: string;
};

const BADGE_COLORS: Record<string, string> = {
  "8-K": "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
  "10-K": "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  "10-Q": "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  "news": "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

function edgarUrl(accession: string): string {
  const clean = accession.replace(/-/g, "");
  return `https://www.sec.gov/Archives/edgar/data/0/${clean}/`;
}

export function SourceCard({ citation }: { citation: Citation }) {
  const isNews = citation.form_type === "news";
  const badgeClass =
    BADGE_COLORS[citation.form_type] ??
    "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  const short = citation.accession_number.slice(0, 22) + (citation.accession_number.length > 22 ? "…" : "");
  const href = citation.source_url || (isNews ? "#" : edgarUrl(citation.accession_number));

  return (
    <div className="rounded-md border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${badgeClass}`}>
          {citation.form_type || "SEC"}
        </span>
        <span className="text-zinc-500 dark:text-zinc-400">{citation.date}</span>
        {!isNews && <span className="ml-auto font-mono text-[10px] text-zinc-400">{short}</span>}
      </div>
      {citation.excerpt && (
        <p className="mt-1 line-clamp-2 text-zinc-600 dark:text-zinc-400">
          {citation.excerpt}
        </p>
      )}
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 inline-block text-emerald-600 hover:underline dark:text-emerald-400"
      >
        {isNews ? "Read article ↗" : "View filing ↗"}
      </a>
    </div>
  );
}
