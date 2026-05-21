import type { KeywordStatus } from "../api";

type Props = {
  keywords: KeywordStatus[];
};

export default function KeywordsPanel({ keywords }: Props) {
  return (
    <div className="grid grid-cols-2 gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 md:grid-cols-4">
      {keywords.map((keyword) => (
        <div
          key={keyword.value}
          className={`rounded-full px-3 py-2 text-center text-xs font-medium ${
            keyword.is_indexed
              ? "bg-emerald-900/50 text-emerald-300"
              : "bg-amber-900/50 text-amber-300"
          }`}
        >
          {keyword.value}
        </div>
      ))}
    </div>
  );
}
