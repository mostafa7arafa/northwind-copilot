"use client";

import { Database, FilePlus2, Unplug } from "lucide-react";
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
  onSelect: (id: string | null) => void;
}) {
  const [datasets, setDatasets] = useState<DatasetMeta[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // Which dataset the next picked file should be APPENDED to (multi-file
  // datasets: the file's tables join the dataset instead of creating a new
  // one). Null = the picker creates a new dataset.
  const appendTo = useRef<string | null>(null);

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
    const target = appendTo.current;
    appendTo.current = null;
    setBusy(true);
    setError("");
    try {
      if (target) {
        // Append: the file's tables join the existing dataset (so questions
        // can join across files).
        await datasetsApi.addFile(target, file);
        await refresh();
        onSelect(target);
      } else {
        const ds = await datasetsApi.upload(file, file.name.replace(/\.[^.]+$/, ""));
        await refresh();
        if (ds.status === "ready") onSelect(ds.id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(id: string) {
    await datasetsApi.remove(id);
    // Deleting the connected dataset disconnects it (back to the sample DB).
    if (id === activeId) onSelect(null);
    await refresh();
  }

  const active = datasets.find((d) => d.id === activeId) ?? null;

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
          aria-label="Upload dataset file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
          }}
        />
      </div>

      {/* What the analyst is connected to right now. Questions always run
          against exactly one source: the selected dataset, or the built-in
          sample database when nothing is selected. */}
      <div className="rounded-[var(--radius-card)] border border-hairline bg-surface px-2.5 py-2">
        <div className="flex items-center gap-1.5 text-[12.5px] text-ink">
          <Database size={13} className="shrink-0 text-electric" />
          <span className="eyebrow">Connected to</span>
        </div>
        {active ? (
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="truncate text-[12.5px] text-ink" title={active.name}>
              {active.name}
              <span className="text-ink-dim"> · {active.row_count} rows</span>
            </span>
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-ink-dim transition-colors hover:bg-surface-2 hover:text-[var(--color-err)]"
              title="Disconnect this dataset (questions will use the sample database)"
            >
              <Unplug size={11} /> Disconnect
            </button>
          </div>
        ) : (
          <p className="mt-1 text-[11.5px] leading-relaxed text-ink-dim">
            Sample database (Northwind demo). Upload and select your own data to
            chat with it instead.
          </p>
        )}
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
            {d.status === "ready" && (
              <button
                type="button"
                onClick={() => {
                  appendTo.current = d.id;
                  fileRef.current?.click();
                }}
                disabled={busy}
                className="ml-2 text-ink-dim hover:text-electric disabled:opacity-50"
                title={`Add a file to ${d.name} — its tables join this dataset`}
                aria-label={`Add file to ${d.name}`}
              >
                <FilePlus2 size={13} />
              </button>
            )}
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
