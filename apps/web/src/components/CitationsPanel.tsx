"use client";

import { useState } from "react";
import { SourceCard } from "./SourceCard";

type Citation = {
  accession_number: string;
  date: string;
  form_type: string;
  excerpt?: string;
  source_url?: string;
};

export function CitationsPanel({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState(false);
  if (!citations.length) return null;

  return (
    <div className="mt-2 text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-zinc-400 underline-offset-2 hover:text-zinc-600 hover:underline dark:hover:text-zinc-200"
      >
        {open ? "Hide sources" : `${citations.length} source${citations.length !== 1 ? "s" : ""}`}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {citations.map((c, i) => (
            <SourceCard key={i} citation={c} />
          ))}
        </div>
      )}
    </div>
  );
}
