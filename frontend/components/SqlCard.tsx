"use client";

import Editor from "@monaco-editor/react";
import { Download, Expand, Maximize2, Minimize2 } from "lucide-react";
import { useState } from "react";
import { CopyButton, GhostButton, Modal, Panel } from "./primitives";

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

/** The generated SQL in a read-only Monaco editor with copy / expand / fullscreen / download. */
export function SqlCard({ sql, tint }: { sql: string; tint: string }) {
  const [expanded, setExpanded] = useState(false);
  const [full, setFull] = useState(false);
  const lines = sql.split("\n").length;
  const height = expanded ? Math.min(lines * 20 + 24, 520) : Math.min(lines * 20 + 24, 200);

  return (
    <Panel
      eyebrow="SQL"
      title={<span className="tape text-ink-dim">generated query</span>}
      actions={
        <>
          <GhostButton
            title="Download .sql"
            onClick={() => {
              const blob = new Blob([sql], { type: "text/sql" });
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
          <CopyButton text={sql} />
        </>
      }
    >
      <div style={{ borderLeft: `2px solid ${tint}` }}>
        <Editor
          height={height}
          language="sql"
          theme="vs-dark"
          value={sql}
          options={EDITOR_OPTIONS}
          loading={<div className="p-4 text-[12px] text-ink-faint">Loading editor…</div>}
          onMount={(_e, monaco) => applyDeskTheme(monaco)}
        />
      </div>

      {full && (
        <Modal title="SQL · Esc to close" onClose={() => setFull(false)}>
          <div className="h-full overflow-hidden rounded-[var(--radius-card)] border border-hairline">
            <Editor
              height="100%"
              language="sql"
              theme="vs-dark"
              value={sql}
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
