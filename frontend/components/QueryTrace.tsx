"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  BarChart3,
  Check,
  Database,
  Lightbulb,
  Search,
  SquareCode,
  Table2,
} from "lucide-react";
import type { Engine, StageId, Turn } from "@/lib/types";
import { cn } from "@/lib/cn";

const STATIONS: { id: StageId; label: string; Icon: typeof Search }[] = [
  { id: "understand", label: "Understand", Icon: Search },
  { id: "sql", label: "Write SQL", Icon: SquareCode },
  { id: "execute", label: "Execute", Icon: Database },
  { id: "results", label: "Results", Icon: Table2 },
  { id: "chart", label: "Chart", Icon: BarChart3 },
  { id: "insights", label: "Insights", Icon: Lightbulb },
];

/**
 * The signature rail. A transit line whose stations are the pipeline stages; a
 * pulse of light travels it while the agent works, each station clicks solid as
 * it completes, and the whole rail is tinted by the engine that ran the turn
 * (steel = local, electric = cloud).
 */
export function QueryTrace({ turn }: { turn: Turn }) {
  const engine: Engine = turn.engine ?? "local";
  const tint = engine === "cloud" ? "var(--color-electric)" : "var(--color-steel)";

  // Once the turn has finished, the six-station rail is just noise — the run is
  // over and every station reads the same. Collapse it to a single status disc:
  // a check when it succeeded, an alert when it didn't.
  if (!turn.running) {
    const failed = !!turn.error;
    const color = failed ? "var(--color-err)" : tint;
    return (
      <div className="relative flex w-11 shrink-0 flex-col items-center pt-1">
        <div
          className="flex h-6 w-6 items-center justify-center rounded-full border"
          style={{
            borderColor: color,
            background: failed ? "transparent" : color,
            color: failed ? color : "var(--color-bg)",
            animation: failed ? undefined : "station-pop 0.28s ease-out",
          }}
          title={failed ? "Couldn't complete" : "Done"}
        >
          {failed ? (
            <AlertTriangle size={13} strokeWidth={2.5} />
          ) : (
            <Check size={13} strokeWidth={3} />
          )}
        </div>
      </div>
    );
  }

  const lastActiveIdx = STATIONS.reduce(
    (acc, s, i) => (turn.stages[s.id] !== "idle" ? i : acc),
    0
  );
  const fillPct = (lastActiveIdx / (STATIONS.length - 1)) * 100;

  return (
    <div className="relative flex w-11 shrink-0 flex-col items-center pt-1">
      {/* faint full-height track */}
      <div className="absolute left-1/2 top-3 bottom-3 w-px -translate-x-1/2 bg-hairline" />
      {/* filled progress */}
      <motion.div
        className="absolute left-1/2 top-3 w-px -translate-x-1/2"
        style={{ background: tint, boxShadow: `0 0 8px ${tint}` }}
        initial={{ height: 0 }}
        animate={{ height: `calc(${fillPct}% - 12px)` }}
        transition={{ type: "spring", stiffness: 120, damping: 22 }}
      />
      {/* traveling pulse while running */}
      {turn.running && (
        <div
          className="absolute left-1/2 h-8 w-[3px] -translate-x-1/2 rounded-full blur-[1px]"
          style={{
            background: `linear-gradient(to bottom, transparent, ${tint}, transparent)`,
            animation: "rail-pulse 1.5s ease-in-out infinite",
          }}
        />
      )}

      <div className="relative flex flex-1 flex-col justify-between gap-2">
        {STATIONS.map(({ id, label, Icon }) => {
          const status = turn.stages[id];
          const done = status === "done";
          const active = status === "active";
          return (
            <div key={id} className="group relative flex items-center justify-center">
              <div
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full border transition-colors",
                  done && "text-bg",
                  active && "text-ink",
                  status === "idle" && "border-hairline bg-surface text-ink-faint"
                )}
                style={{
                  borderColor: done || active ? tint : undefined,
                  background: done ? tint : active ? "var(--color-surface-2)" : undefined,
                  boxShadow: active ? `0 0 0 4px ${tint}22` : undefined,
                  animation: done ? "station-pop 0.28s ease-out" : undefined,
                }}
              >
                {done ? (
                  <Check size={13} strokeWidth={3} />
                ) : active ? (
                  <span
                    className="dot-live block h-2 w-2 rounded-full"
                    style={{ background: tint }}
                  />
                ) : (
                  <Icon size={12} />
                )}
              </div>
              {/* station label on hover */}
              <span className="pointer-events-none absolute left-8 z-10 whitespace-nowrap rounded-md border border-hairline bg-surface-2 px-2 py-1 text-[11px] text-ink-dim opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
