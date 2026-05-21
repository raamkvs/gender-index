import { useEffect, useRef } from "react";

type LogType = "ok" | "skip" | "new" | "error";

export type LogLine = {
  line: string;
  type: LogType;
};

type Props = {
  lines: LogLine[];
  syncing: boolean;
  onRunSync: () => void;
  onReindexAll: () => void;
};

const styleMap: Record<LogType, string> = {
  ok: "text-emerald-400",
  skip: "text-slate-400",
  new: "text-violet-300",
  error: "text-red-400",
};

export default function SyncLog({ lines, syncing, onRunSync, onReindexAll }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-slate-200">
          <span>Sync log</span>
          {syncing && (
            <span className="flex items-center gap-2 text-xs text-slate-400">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
              syncing...
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            className="rounded bg-slate-700 px-3 py-1 text-xs text-slate-100 hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={syncing}
            onClick={onReindexAll}
          >
            reindex all
          </button>
          <button
            className="rounded bg-indigo-600 px-3 py-1 text-xs text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={syncing}
            onClick={onRunSync}
          >
            run sync
          </button>
        </div>
      </div>
      <div
        ref={containerRef}
        className="h-[180px] overflow-y-auto rounded border border-slate-800 bg-slate-950 p-2 font-mono text-xs"
      >
        {lines.length === 0 && <p className="text-slate-500">No sync logs yet.</p>}
        {lines.map((entry, idx) => (
          <p key={`${entry.line}-${idx}`} className={styleMap[entry.type]}>
            {entry.line}
          </p>
        ))}
      </div>
    </section>
  );
}
