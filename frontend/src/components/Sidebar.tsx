import type { IndexInfo } from "../api";

type Props = {
  indexes: IndexInfo[];
  selectedIndex: string | null;
  onSelectIndex: (name: string) => void;
};

const dotClass: Record<IndexInfo["status"], string> = {
  green: "bg-emerald-400",
  yellow: "bg-amber-400",
  red: "bg-red-400",
};

export default function Sidebar({ indexes, selectedIndex, onSelectIndex }: Props) {
  return (
    <aside className="w-72 border-r border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-300">
        Elasticsearch Indexes
      </h2>
      <div className="space-y-2">
        {indexes.map((index) => (
          <button
            key={index.name}
            className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm ${
              selectedIndex === index.name
                ? "bg-slate-700 text-white"
                : "bg-slate-800/50 text-slate-200 hover:bg-slate-800"
            }`}
            onClick={() => onSelectIndex(index.name)}
          >
            <span className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${dotClass[index.status]}`} />
              {index.name}
            </span>
            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs">{index.doc_count}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
