import { useEffect, useMemo, useState } from "react";
import {
  getDocuments,
  getIndexes,
  getKeywords,
  reindexDoc,
  runSync,
  runSyncAll,
  type DocumentStatus,
  type IndexInfo,
  type KeywordStatus,
} from "./api";
import DocumentsTable from "./components/DocumentsTable";
import KeywordsPanel from "./components/KeywordsPanel";
import Sidebar from "./components/Sidebar";
import StatBar from "./components/StatBar";
import SyncLog, { type LogLine } from "./components/SyncLog";

type Tab = "documents" | "keywords";

export default function App() {
  const [indexes, setIndexes] = useState<IndexInfo[]>([]);
  const [documents, setDocuments] = useState<DocumentStatus[]>([]);
  const [keywords, setKeywords] = useState<KeywordStatus[]>([]);
  const [tab, setTab] = useState<Tab>("documents");
  const [selectedIndex, setSelectedIndex] = useState<string | null>(null);
  const [busyDocId, setBusyDocId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [logs, setLogs] = useState<LogLine[]>([]);

  const [loadingIndexes, setLoadingIndexes] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [loadingKeywords, setLoadingKeywords] = useState(false);
  const [errorIndexes, setErrorIndexes] = useState<string | null>(null);
  const [errorDocuments, setErrorDocuments] = useState<string | null>(null);
  const [errorKeywords, setErrorKeywords] = useState<string | null>(null);

  const loadIndexes = async () => {
    setLoadingIndexes(true);
    setErrorIndexes(null);
    try {
      const data = await getIndexes();
      setIndexes(data);
      setSelectedIndex((prev) => prev ?? data[0]?.name ?? null);
    } catch (error) {
      setErrorIndexes((error as Error).message);
    } finally {
      setLoadingIndexes(false);
    }
  };

  const loadDocuments = async () => {
    setLoadingDocuments(true);
    setErrorDocuments(null);
    try {
      const data = await getDocuments();
      setDocuments(data);
    } catch (error) {
      setErrorDocuments((error as Error).message);
    } finally {
      setLoadingDocuments(false);
    }
  };

  const loadKeywords = async () => {
    setLoadingKeywords(true);
    setErrorKeywords(null);
    try {
      const data = await getKeywords();
      setKeywords(data);
    } catch (error) {
      setErrorKeywords((error as Error).message);
    } finally {
      setLoadingKeywords(false);
    }
  };

  const refreshAll = async () => {
    await Promise.all([loadIndexes(), loadDocuments(), loadKeywords()]);
  };

  useEffect(() => {
    void refreshAll();
  }, []);

  const onReindexDoc = async (docId: string) => {
    setBusyDocId(docId);
    try {
      await reindexDoc(docId);
      await refreshAll();
    } catch (error) {
      setLogs((prev) => [...prev, { line: `Reindex failed: ${(error as Error).message}`, type: "error" }]);
    } finally {
      setBusyDocId(null);
    }
  };

  const startSync = (all: boolean) => {
    if (syncing) {
      return;
    }
    setSyncing(true);
    const source = all ? runSyncAll() : runSync();
    setLogs((prev) => [...prev, { line: all ? "Starting full reindex..." : "Starting incremental sync...", type: "new" }]);

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as LogLine;
        setLogs((prev) => [...prev, data]);
      } catch {
        setLogs((prev) => [...prev, { line: event.data, type: "skip" }]);
      }
    };

    source.onerror = () => {
      source.close();
      setSyncing(false);
      void refreshAll();
    };
  };

  const runSyncWithUi = () => startSync(false);

  const runSyncAllWithUi = () => {
    const confirmed = window.confirm("This will clear state and re-index all data. Continue?");
    if (!confirmed) {
      return;
    }
    startSync(true);
  };

  const panelLoading = loadingDocuments || loadingKeywords;
  const panelError = tab === "documents" ? errorDocuments : errorKeywords;

  const selectedSummary = useMemo(() => {
    if (!selectedIndex) {
      return "No index selected";
    }
    return `Selected index: ${selectedIndex}`;
  }, [selectedIndex]);

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <Sidebar indexes={indexes} selectedIndex={selectedIndex} onSelectIndex={setSelectedIndex} />

      <main className="flex flex-1 flex-col p-4">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold">Document Indexer</h1>
          <p className="text-sm text-slate-400">{selectedSummary}</p>
          {loadingIndexes && <p className="text-xs text-slate-400">Loading indexes...</p>}
          {errorIndexes && <p className="text-xs text-red-400">Index API error: {errorIndexes}</p>}
        </header>

        <div className="mb-4">
          <StatBar documents={documents} />
        </div>

        <div className="mb-3 flex items-center gap-2">
          <button
            className={`rounded px-3 py-1 text-sm ${
              tab === "documents" ? "bg-indigo-600" : "bg-slate-800 hover:bg-slate-700"
            }`}
            onClick={() => setTab("documents")}
          >
            Documents
          </button>
          <button
            className={`rounded px-3 py-1 text-sm ${
              tab === "keywords" ? "bg-indigo-600" : "bg-slate-800 hover:bg-slate-700"
            }`}
            onClick={() => setTab("keywords")}
          >
            Keywords
          </button>
        </div>

        <section className="mb-4 flex-1">
          {panelLoading && <p className="text-sm text-slate-400">Loading {tab}...</p>}
          {panelError && <p className="text-sm text-red-400">Error loading {tab}: {panelError}</p>}
          {!panelLoading && !panelError && tab === "documents" && (
            <DocumentsTable documents={documents} onReindex={onReindexDoc} busyDocId={busyDocId} />
          )}
          {!panelLoading && !panelError && tab === "keywords" && <KeywordsPanel keywords={keywords} />}
        </section>

        <SyncLog
          lines={logs}
          syncing={syncing}
          onRunSync={runSyncWithUi}
          onReindexAll={runSyncAllWithUi}
        />
      </main>
    </div>
  );
}
