"use client";

import Editor from "@monaco-editor/react";
import { Download, Expand, Maximize2, Minimize2, Pencil, Play, Undo2 } from "lucide-react";
import { useState } from "react";
import { ApiError, datasetsApi } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { TableData } from "@/lib/types";
import { CopyButton, GhostButton, Modal, Panel } from "./primitives";
import { ResultsTable } from "./ResultsTable";

const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";

const EDITOR_OPTIONS = {
  readOnly: true,
  minimap: { enabled: false },
  fontSize: 13,
  fontFamily: "var(--font-jetbrains), monospace",
  lineNumbers: "on" as const,
  scrollBeyondLastLine: false,
  padding: { top: 12, bottom: 12 },
  renderLineHighlight: "none" as const,
  scrollbar: { vertical: "auto" as const, verticalScrollbarSize: 8 },
  overviewRulerLanes: 0,
  guides: { indentation: false },
  wordWrap: "on" as const,
};

/** Register and apply the dark "desk" editor theme. `monaco` is the instance
 * @monaco-editor/react hands to onMount; typed loosely to avoid a hard
 * dependency on monaco-editor's type package. */
const applyDeskTheme = (monaco: {
  editor: {
    defineTheme: (name: string, theme: unknown) => void;
    setTheme: (name: string) => void;
  };
}) => {
  monaco.editor.defineTheme("desk", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#0d0f14",
      "editorLineNumber.foreground": "#3a3f4b",
      "editorGutter.background": "#0d0f14",
    },
  });
  monaco.editor.setTheme("desk");
};

/** The generated SQL in a Monaco editor with copy / expand / fullscreen /
 * download — plus, on a hosted dataset, an edit-and-re-run mode: fix the
 * query in place and execute it through the same read-only, time-boxed path
 * the agent uses. Edited runs render their result inline and are never
 * written back into the conversation. */
export function SqlCard({ sql, tint }: { sql: string; tint: string }) {
  const activeDatasetId = useStore((s) => s.activeDatasetId);
  const [expanded, setExpanded] = useState(false);
  const [full, setFull] = useState(false);
  // Edit & re-run state (hosted datasets only).
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sql);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TableData | null>(null);
  const [runError, setRunError] = useState("");
  // Monaco's real content height accounts for word-wrapped long lines, which a
  // raw newline count misses — a two-line-but-very-long query still needs room.
  const [contentH, setContentH] = useState(0);
  const shown = editing ? draft : sql;
  const lines = shown.split("\n").length;
  const natural = contentH > 0 ? contentH + 8 : lines * 20 + 24;
  const height = expanded
    ? Math.min(Math.max(natural, 240), 600)
    : Math.min(Math.max(natural, editing ? 120 : 0), 200);

  const editable = HOSTED && !!activeDatasetId;

  const startEdit = () => {
    setDraft(sql);
    setResult(null);
    setRunError("");
    setEditing(true);
  };

  const stopEdit = () => {
    setEditing(false);
    setResult(null);
    setRunError("");
  };

  const run = async () => {
    if (!activeDatasetId || !draft.trim()) return;
    setRunning(true);
    setRunError("");
    try {
      setResult(await datasetsApi.query(activeDatasetId, draft));
    } catch (err) {
      setResult(null);
      setRunError(
        err instanceof ApiError ? err.message : "The query couldn't be run."
      );
    } finally {
      setRunning(false);
    }
  };

  /** Register the theme and start tracking content height (recomputes on wrap). */
  const onEditorMount = (
    editor: { onDidContentSizeChange: (cb: () => void) => void; getContentHeight: () => number },
    monaco: Parameters<typeof applyDeskTheme>[0]
  ) => {
    applyDeskTheme(monaco);
    const sync = () => setContentH(editor.getContentHeight());
    editor.onDidContentSizeChange(sync);
    sync();
  };

  return (
    <Panel
      eyebrow="SQL"
      title={
        <span className="tape text-ink-dim">
          {editing ? "editing — runs against your dataset" : "generated query"}
        </span>
      }
      actions={
        <>
          {editable && !editing && (
            <GhostButton title="Edit & re-run" onClick={startEdit}>
              <Pencil size={13} />
            </GhostButton>
          )}
          {editing && (
            <>
              <GhostButton title="Run edited query" onClick={run}>
                <Play size={13} /> {running ? "Running…" : "Run"}
              </GhostButton>
              <GhostButton title="Back to the original query" onClick={stopEdit}>
                <Undo2 size={13} />
              </GhostButton>
            </>
          )}
          <GhostButton
            title="Download .sql"
            onClick={() => {
              const blob = new Blob([shown], { type: "text/sql" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = "query.sql";
              a.click();
            }}
          >
            <Download size={13} />
          </GhostButton>
          <GhostButton
            title={expanded ? "Collapse" : "Expand"}
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </GhostButton>
          <GhostButton title="Fullscreen" onClick={() => setFull(true)}>
            <Expand size={13} />
          </GhostButton>
          <CopyButton text={shown} />
        </>
      }
    >
      <div style={{ borderLeft: `2px solid ${editing ? "var(--color-warn, #eab308)" : tint}` }}>
        <Editor
          height={height}
          language="sql"
          theme="vs-dark"
          value={shown}
          options={{ ...EDITOR_OPTIONS, readOnly: !editing }}
          onChange={(v) => editing && setDraft(v ?? "")}
          loading={<div className="p-4 text-[12px] text-ink-faint">Loading editor…</div>}
          onMount={onEditorMount}
        />
      </div>

      {editing && runError && (
        <p className="border-t border-hairline px-3 py-2 text-[12px] text-warn">
          {runError}
        </p>
      )}
      {editing && result && (
        <div className="border-t border-hairline p-2">
          <p className="mb-1 px-1 text-[11px] text-ink-faint">
            Edited run — shown here only, not saved to the conversation.
          </p>
          <ResultsTable data={result} />
        </div>
      )}

      {full && (
        <Modal title="SQL · Esc to close" onClose={() => setFull(false)}>
          <div className="h-full overflow-hidden rounded-[var(--radius-card)] border border-hairline">
            <Editor
              height="100%"
              language="sql"
              theme="vs-dark"
              value={shown}
              options={EDITOR_OPTIONS}
              loading={<div className="p-4 text-[12px] text-ink-faint">Loading editor…</div>}
              onMount={(_e, monaco) => applyDeskTheme(monaco)}
            />
          </div>
        </Modal>
      )}
    </Panel>
  );
}
