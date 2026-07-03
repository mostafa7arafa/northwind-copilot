"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, datasetsApi } from "@/lib/api";
import type { DatasetMeta } from "@/lib/types";

/**
 * Dataset manager: upload CSV/Excel/SQLite files, see ingestion status, edit a
 * dataset's business context, pick the active dataset, and delete. Self-contained
 * (drives its own list via the datasets API) so it can drop into the app shell.
 */
export function DatasetManager({
  activeId,
  onSelect,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [datasets, setDatasets] = useState<DatasetMeta[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      setDatasets(await datasetsApi.list());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setError("Couldn't load datasets.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onUpload(file: File) {
    setBusy(true);
    setError("");
    try {
      const ds = await datasetsApi.upload(file, file.name.replace(/\.[^.]+$/, ""));
      await refresh();
      if (ds.status === "ready") onSelect(ds.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(id: string) {
    await datasetsApi.remove(id);
    await refresh();
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">Datasets</h2>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="rounded-[var(--radius-card)] bg-electric px-2.5 py-1 text-xs font-medium text-bg disabled:opacity-60"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.tsv,.xlsx,.xls,.sqlite,.sqlite3,.db"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
          }}
        />
      </div>

      {error && <p className="text-xs text-[var(--color-err)]">{error}</p>}

      <ul className="space-y-1">
        {datasets.map((d) => (
          <li
            key={d.id}
            className={`flex items-center justify-between rounded-[var(--radius-card)] border px-2.5 py-2 text-sm ${
              d.id === activeId
                ? "border-hairline-strong bg-surface"
                : "border-hairline"
            }`}
          >
            <button
              className="flex-1 truncate text-left text-ink disabled:text-ink-dim"
              disabled={d.status !== "ready"}
              onClick={() => onSelect(d.id)}
              title={d.name}
            >
              {d.name}{" "}
              <span className="text-xs text-ink-dim">
                {d.status === "ready"
                  ? `· ${d.row_count} rows`
                  : d.status === "failed"
                  ? "· failed"
                  : "· processing…"}
              </span>
            </button>
            <button
              onClick={() => onDelete(d.id)}
              className="ml-2 text-xs text-ink-dim hover:text-[var(--color-err)]"
              aria-label={`Delete ${d.name}`}
            >
              ✕
            </button>
          </li>
        ))}
        {datasets.length === 0 && (
          <li className="text-xs text-ink-dim">
            No datasets yet. Upload a CSV, Excel, or SQLite file to start.
          </li>
        )}
      </ul>
    </div>
  );
}
