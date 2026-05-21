import type { DocumentStatus } from "../api";

type Props = {
  documents: DocumentStatus[];
};

function metricCard(label: string, value: number, tone: string) {
  return (
    <div className={`rounded-lg border border-slate-700 bg-slate-900 p-4 ${tone}`}>
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
    </div>
  );
}

export default function StatBar({ documents }: Props) {
  const total = documents.length;
  const indexed = documents.filter((doc) => doc.is_indexed).length;
  const pending = total - indexed;

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {metricCard("Total docs", total, "")}
      {metricCard("Total indexed", indexed, "")}
      {metricCard("Pending", pending, "")}
    </div>
  );
}
