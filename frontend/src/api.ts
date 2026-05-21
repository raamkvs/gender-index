export type IndexInfo = {
  name: string;
  doc_count: number;
  status: "green" | "yellow" | "red";
};

export type DocumentStatus = {
  doc_id: string;
  title: string;
  keywords: string[];
  source: string;
  is_indexed: boolean;
  indexed_at: string | null;
};

export type KeywordStatus = {
  value: string;
  is_indexed: boolean;
  indexed_at: string | null;
};

const toJson = async <T>(res: Response): Promise<T> => {
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
};

export const getIndexes = () => fetch("/api/indexes").then(toJson<IndexInfo[]>);
export const getDocuments = () => fetch("/api/documents").then(toJson<DocumentStatus[]>);
export const getKeywords = () => fetch("/api/keywords").then(toJson<KeywordStatus[]>);
export const reindexDoc = (doc_id: string) =>
  fetch(`/api/documents/${doc_id}/reindex`, { method: "POST" }).then(toJson<DocumentStatus>);
export const runSync = () => new EventSource("/api/sync");
export const runSyncAll = () => new EventSource("/api/sync/all");
