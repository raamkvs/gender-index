import { useMemo, useState } from "react";
import type { DocumentStatus } from "../api";

type Props = {
  documents: DocumentStatus[];
  onReindex: (docId: string) => Promise<void>;
  busyDocId: string | null;
};

export default function DocumentsTable({ documents, onReindex, busyDocId }: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return documents;
    }
    return documents.filter(
      (doc) =>
        doc.title.toLowerCase().includes(q) ||
        doc.keywords.some((keyword) => keyword.toLowerCase().includes(q)),
    );
  }, [documents, query]);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 p-3">
        <input
          className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="Search by title or keyword"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="overflow-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-800 text-slate-300">
            <tr>
              <th className="px-3 py-2">doc_id</th>
              <th className="px-3 py-2">title</th>
              <th className="px-3 py-2">keywords</th>
              <th className="px-3 py-2">status</th>
              <th className="px-3 py-2">action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc) => (
              <tr key={doc.doc_id} className="border-t border-slate-800 text-slate-200">
                <td className="px-3 py-2 font-mono text-xs">{doc.doc_id}</td>
                <td className="px-3 py-2">{doc.title}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {doc.keywords.map((kw) => (
                      <span key={kw} className="rounded bg-slate-700 px-2 py-0.5 text-xs">
                        {kw}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {doc.is_indexed ? (
                    <div>
                      <p className="flex items-center gap-2 text-emerald-400">
                        <span className="h-2 w-2 rounded-full bg-emerald-400" />
                        indexed
                      </p>
                      <p className="text-xs text-slate-400">{doc.indexed_at ?? "-"}</p>
                    </div>
                  ) : (
                    <p className="flex items-center gap-2 text-amber-400">
                      <span className="h-2 w-2 rounded-full bg-amber-400" />
                      pending
                    </p>
                  )}
                </td>
                <td className="px-3 py-2">
                  <button
                    className={`rounded px-3 py-1 text-xs font-medium ${
                      doc.is_indexed
                        ? "bg-slate-700 text-slate-100 hover:bg-slate-600"
                        : "bg-indigo-600 text-white hover:bg-indigo-500"
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                    disabled={busyDocId === doc.doc_id}
                    onClick={() => onReindex(doc.doc_id)}
                  >
                    {busyDocId === doc.doc_id ? "working..." : doc.is_indexed ? "reindex" : "index now"}
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td className="px-3 py-6 text-center text-slate-400" colSpan={5}>
                  No documents match your search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
