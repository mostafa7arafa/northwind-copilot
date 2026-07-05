"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronDown, Cloud, Cpu, Pin } from "lucide-react";
import type { Turn } from "@/lib/types";
import { turnCharts, turnQueries } from "@/lib/types";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/cn";
import { QueryTrace } from "./QueryTrace";
import { SqlCard } from "./SqlCard";
import { ResultsTable } from "./ResultsTable";
import { ChartCard } from "./ChartCard";
import { AnswerBubble } from "./AnswerBubble";
import { ChartSkeleton, SqlSkeleton, TableSkeleton } from "./Skeletons";
import { BrandMark } from "./BrandMark";

// The ledger actually spans 2012–2023, so questions pinned to a year outside it
// (the classic "1997") come back empty. Detect that to nudge instead of leaving a
// blank result — and to head off the model inventing numbers on no rows.
const LEDGER_START = 2012;
const LEDGER_END = 2023;
function strayYear(question: string): number | null {
  const years = question.match(/\b(19|20)\d{2}\b/g);
  if (!years) return null;
  for (const y of years) {
    const n = Number(y);
    if (n < LEDGER_START || n > LEDGER_END) return n;
  }
  return null;
}

const block = {
  initial: { opacity: 0, y: 18 },
  animate: { opacity: 1, y: 0 },
  transition: { type: "spring" as const, stiffness: 180, damping: 26 },
};

function EngineBadge({ turn }: { turn: Turn }) {
  const cloud = turn.engine === "cloud";
  const tint = cloud ? "var(--color-electric)" : "var(--color-steel)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]"
      style={{ borderColor: `${tint}55`, color: tint }}
    >
      {cloud ? <Cloud size={11} /> : <Cpu size={11} />}
      <span className="tape">{turn.model || (cloud ? "cloud" : "local")}</span>
    </span>
  );
}

function statusLabel(turn: Turn): string {
  if (turn.error) return "Couldn't complete";
  if (!turn.running) return "Done";
  const order = ["insights", "chart", "results", "execute", "sql", "understand"] as const;
  const active = order.find((s) => turn.stages[s] === "active");
  const map: Record<string, string> = {
    understand: "Understanding the question",
    sql: "Writing SQL",
    execute: "Running the query",
    results: "Reading results",
    chart: "Drawing the chart",
    insights: "Summarizing",
  };
  return active ? map[active] : "Thinking";
}

/** One assistant turn: the signature rail beside a stack of animated cards. */
export function QueryTurn({ turn }: { turn: Turn }) {
  const toggle = useStore((s) => s.toggleTurn);
  const pin = useStore((s) => s.pinTurn);
  const pinnedId = useStore((s) => s.pinnedTurnId);
  const tint = turn.engine === "cloud" ? "var(--color-electric)" : "var(--color-steel)";
  const queries = turnQueries(turn);
  const charts = turnCharts(turn);
  const hasAnyArtifact = queries.length > 0 || charts.length > 0;
  const showSqlSkeleton = queries.length === 0 && turn.stages.sql === "active";
  const showTableSkeleton =
    !queries.some((q) => q.table) && turn.stages.results === "active";
  const showChartSkeleton = charts.length === 0 && turn.stages.chart === "active";

  const tables = queries.flatMap((q) => (q.table ? [q.table] : []));
  const emptyResult =
    !turn.running &&
    !turn.error &&
    tables.length > 0 &&
    tables.every((t) => t.rows.length === 0);
  const stray = strayYear(turn.question);
  const showWink = emptyResult && stray !== null;

  return (
    <div className="border-b border-hairline/60 py-6">
      {/* question row */}
      <div className="mb-4 flex items-start gap-3">
        <button
          onClick={() => toggle(turn.id)}
          className="mt-0.5 text-ink-faint transition-colors hover:text-ink"
          aria-label={turn.collapsed ? "Expand" : "Collapse"}
        >
          <ChevronDown
            size={18}
            className={cn("transition-transform", turn.collapsed && "-rotate-90")}
          />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="tape text-[17px] leading-snug text-ink">{turn.question}</h2>
          <div className="mt-1.5 flex items-center gap-2.5">
            {turn.engine && <EngineBadge turn={turn} />}
            <span className="flex items-center gap-1.5 text-[12px] text-ink-dim">
              {turn.running && (
                <span
                  className="dot-live h-1.5 w-1.5 rounded-full"
                  style={{ background: tint }}
                />
              )}
              {statusLabel(turn)}
            </span>
          </div>
        </div>
        {hasAnyArtifact && (
          <button
            type="button"
            onClick={() => pin(pinnedId === turn.id ? null : turn.id)}
            title="Pin artifact to the side"
            className={cn(
              "rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink",
              pinnedId === turn.id && "text-electric"
            )}
          >
            <Pin size={14} />
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {!turn.collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="flex gap-1">
              <QueryTrace turn={turn} />
              <div className="min-w-0 flex-1 space-y-3 pt-1">
                {turn.error && (
                  <motion.div {...block}>
                    <div className="rounded-[var(--radius-card)] border border-err/40 bg-err/5 p-4">
                      <div className="flex items-center gap-2 text-err">
                        <AlertTriangle size={15} />
                        <span className="text-[14px] font-medium">{turn.error.message}</span>
                      </div>
                      {turn.error.detail && (
                        <p className="mt-2 tape text-[12px] leading-relaxed text-ink-dim">
                          {turn.error.detail}
                        </p>
                      )}
                      <p className="mt-2 text-[12.5px] text-ink-dim">
                        Try rephrasing, or switch engine in the header and ask again.
                      </p>
                    </div>
                  </motion.div>
                )}

                {showWink && (
                  <motion.div {...block}>
                    <div className="flex items-center gap-3 rounded-[var(--radius-card)] border border-hairline bg-surface-2/60 p-4">
                      <BrandMark engine={turn.engine ?? "local"} size={34} className="shrink-0" />
                      <p className="text-[13px] leading-relaxed text-ink-dim">
                        Nothing shipped in{" "}
                        <span className="tape text-ink">{stray}</span> — this ledger
                        runs <span className="tape text-ink">2012–2023</span>. Try a year
                        in range and the octopus will find it.
                      </p>
                    </div>
                  </motion.div>
                )}

                {/* SQL / results / chart live in the artifact workspace on wide
                    screens; shown inline only below lg, where no panel exists. */}
                <div className="space-y-3 lg:hidden">
                  {queries.map((q, i) => (
                    <motion.div key={i} {...block} className="space-y-3">
                      {q.sql && <SqlCard sql={q.sql} tint={tint} />}
                      {q.table && <ResultsTable data={q.table} />}
                    </motion.div>
                  ))}
                  {showSqlSkeleton && <SqlSkeleton />}
                  {showTableSkeleton && <TableSkeleton />}

                  {charts.map((c, i) => (
                    <motion.div key={i} {...block}>
                      <ChartCard option={c.option} inferred={c.inferred} />
                    </motion.div>
                  ))}
                  {showChartSkeleton && <ChartSkeleton />}
                </div>

                {turn.insights && (turn.insights.text || turn.insights.bullets.length) && (
                  <motion.div {...block}>
                    <AnswerBubble
                      text={turn.insights.text}
                      bullets={turn.insights.bullets}
                      tint={tint}
                    />
                  </motion.div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
