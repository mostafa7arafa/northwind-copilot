"use client";

import { Gauge } from "lucide-react";
import { useStore } from "@/lib/store";

const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";

/** Header pill showing the org's remaining allowance.
 *
 * Trial orgs see queries left ("18/30 queries"); paid orgs see the credit
 * balance against the monthly grant; orgs running fully on their own keys see
 * a BYOK badge instead of a number. Values come from GET /api/usage on load
 * and are live-updated by the `usage` SSE event after each turn.
 */
export function UsageMeter() {
  const usage = useStore((s) => s.usage);
  if (!HOSTED || !usage) return null;

  const trial = usage.plan === "trial";
  const byokOnly = !trial && usage.byok_providers.length > 0;

  let label: string;
  let ratio: number | null = null;
  if (trial) {
    const left = Math.max(0, usage.trial_queries_limit - usage.trial_queries_used);
    label = `${left}/${usage.trial_queries_limit} queries`;
    ratio = usage.trial_queries_limit
      ? left / usage.trial_queries_limit
      : null;
  } else if (byokOnly) {
    label = "BYOK";
  } else {
    label = `${Math.max(0, Math.floor(usage.credits_remaining))} credits`;
    ratio = usage.credits_per_month
      ? Math.max(0, usage.credits_remaining) / usage.credits_per_month
      : null;
  }

  const low = ratio !== null && ratio < 0.15;

  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-hairline bg-surface px-2.5 py-1.5"
      title={
        trial
          ? "Trial allowance — remaining questions"
          : byokOnly
          ? "Running on your own API key"
          : "Credits remaining this billing period"
      }
    >
      <Gauge size={13} className={low ? "text-warn" : "text-electric"} />
      <span className="tape text-[11.5px] text-ink-dim">
        <span className="eyebrow mr-1.5">{usage.plan}</span>
        <span className={low ? "text-warn" : "text-ink"}>{label}</span>
      </span>
      {ratio !== null && (
        <span className="h-1 w-12 overflow-hidden rounded-full bg-surface-2">
          <span
            className={`block h-full rounded-full ${low ? "bg-warn" : "bg-electric"}`}
            style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
          />
        </span>
      )}
    </div>
  );
}
