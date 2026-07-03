"use client";

import { motion } from "framer-motion";
import { CornerDownLeft, Loader2, Radar, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/cn";

const SUGGESTIONS = [
  "Revenue by category",
  "Top customers by spend",
  "Monthly orders in 2017",
  "Which shipper is fastest?",
];

/** The prompt bar: auto-growing input, suggestion pills, Enter to run. */
export function Composer({ busy }: { busy: boolean }) {
  const ask = useStore((s) => s.ask);
  const kbHint = useStore((s) => s.kbHint);
  const toggleKbHint = useStore((s) => s.toggleKbHint);
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [value]);

  const submit = () => {
    if (!value.trim() || busy) return;
    ask(value);
    setValue("");
  };

  return (
    <div className="shrink-0 border-t border-hairline bg-bg/80 px-4 pb-4 pt-3 backdrop-blur-md">
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <motion.button
              key={s}
              whileHover={{ y: -1 }}
              onClick={() => setValue(s)}
              className="rounded-full border border-hairline bg-surface px-3 py-1 text-[12px] text-ink-dim transition-colors hover:border-electric/40 hover:text-ink"
            >
              {s}
            </motion.button>
          ))}
        </div>

        <div className="focus-glow flex items-end gap-2 rounded-2xl border border-hairline bg-surface px-3 py-2.5 transition-shadow">
          <button
            type="button"
            onClick={toggleKbHint}
            aria-pressed={kbHint ? "true" : "false"}
            title={
              kbHint
                ? "Knowledge base on — the octopus may consult the docs"
                : "Consult the knowledge base"
            }
            className={cn(
              "mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors",
              kbHint
                ? "border-electric/50 bg-electric/10 text-electric"
                : "border-hairline text-ink-faint hover:text-ink"
            )}
          >
            <Radar size={16} className={cn(kbHint && "dot-live")} />
          </button>
          <textarea
            ref={ref}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Ask the ledger…  (e.g. gross margin by category in 1997)"
            className="max-h-[200px] flex-1 resize-none bg-transparent text-[15px] leading-relaxed text-ink outline-none placeholder:text-ink-faint"
          />
          <button
            onClick={submit}
            disabled={!value.trim() || busy}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-electric px-3.5 text-[13px] font-medium text-bg transition-all enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Send size={15} />
            )}
            Run
          </button>
        </div>
        <div className="mt-1.5 flex items-center gap-1 px-1 text-[11px] text-ink-faint">
          <CornerDownLeft size={11} /> to run · Shift + Enter for a new line
        </div>
      </div>
    </div>
  );
}
