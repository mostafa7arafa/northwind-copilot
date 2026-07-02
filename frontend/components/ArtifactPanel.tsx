"use client";

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import type { Turn } from "@/lib/types";
import { useStore } from "@/lib/store";
import { ChartCard } from "./ChartCard";
import { ResultsTable } from "./ResultsTable";
import { SqlCard } from "./SqlCard";
import { ChartSkeleton, SqlSkeleton, TableSkeleton } from "./Skeletons";

const hasArtifact = (t: Turn) => !!(t.sql || t.table || t.chart);

/** The right-docked artifact canvas — the analysis workspace. SQL, results, and
 * the chart live here (not in the chat thread) so the conversation stays a clean
 * Q&A. Follows the pinned turn, else the latest turn that is producing output. */
export function ArtifactPanel() {
  const { sessions, currentId, pinnedTurnId, pinTurn } = useStore();
  const session = sessions.find((s) => s.id === currentId);
  const turns = session?.turns ?? [];

  // Pinned turn wins; otherwise track the most recent turn with (or building)
  // an artifact, so the panel streams the live answer as it arrives.
  const focus = pinnedTurnId
    ? turns.find((t) => t.id === pinnedTurnId)
    : [...turns].reverse().find((t) => hasArtifact(t) || t.running);

  const show = !!focus && (hasArtifact(focus) || focus.running);
  const tint =
    focus?.engine === "cloud" ? "var(--color-electric)" : "var(--color-steel)";

  const showSqlSkeleton = !!focus && !focus.sql && focus.stages.sql === "active";
  const showTableSkeleton =
    !!focus && !focus.table && focus.stages.results === "active";
  const showChartSkeleton =
    !!focus && !focus.chart && focus.stages.chart === "active";

  return (
    <AnimatePresence initial={false}>
      {show && focus && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 460, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ type: "spring", stiffness: 240, damping: 30 }}
          className="hidden shrink-0 overflow-hidden border-l border-hairline bg-surface/30 lg:block"
        >
          <div className="flex h-full w-[460px] flex-col">
            <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
              <div className="min-w-0">
                <div className="eyebrow">
                  {pinnedTurnId ? "Pinned artifact" : "Workspace"}
                </div>
                <div className="tape mt-0.5 truncate text-[12.5px] text-ink-dim">
                  {focus.question}
                </div>
              </div>
              {pinnedTurnId && (
                <button
                  type="button"
                  onClick={() => pinTurn(null)}
                  className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                  title="Unpin (follow latest)"
                >
                  <X size={15} />
                </button>
              )}
            </div>
            <div className="flex-1 space-y-3 overflow-auto p-4">
              {focus.sql && <SqlCard sql={focus.sql} tint={tint} />}
              {showSqlSkeleton && <SqlSkeleton />}

              {focus.table && <ResultsTable data={focus.table} />}
              {showTableSkeleton && <TableSkeleton />}

              {focus.chart && (
                <ChartCard option={focus.chart} inferred={!!focus.chartInferred} />
              )}
              {showChartSkeleton && <ChartSkeleton />}

              {focus.running &&
                !focus.sql &&
                !showSqlSkeleton &&
                !showTableSkeleton &&
                !showChartSkeleton && (
                  <div className="tape text-[12px] text-ink-faint">
                    Working on the query…
                  </div>
                )}
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
