"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useStore } from "@/lib/store";
import { BrandMark } from "./BrandMark";

/**
 * Two rewards, kept quiet until earned:
 *  • type "kraken"      → the octopus releases an ink wash across the screen
 *  • every 10th analysis → a brief "deeper water" nod from the octopus
 */
export function EasterEggs() {
  const inkRef = useRef<HTMLDivElement>(null);
  const engine = useStore((s) => s.engine);
  const queryCount = useStore((s) => s.queryCount);

  // ── kraken ──────────────────────────────────────────────────────────────
  useEffect(() => {
    let buf = "";
    const onKey = (e: KeyboardEvent) => {
      // ignore while typing in the composer or any field
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable))
        return;
      buf = (buf + e.key).slice(-6).toLowerCase();
      if (buf.includes("kraken")) {
        const node = inkRef.current;
        if (!node) return;
        node.classList.remove("go");
        void node.offsetWidth; // restart the animation
        node.classList.add("go");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── milestone nod ───────────────────────────────────────────────────────
  const [nod, setNod] = useState(false);
  const prev = useRef(queryCount);
  useEffect(() => {
    const crossed =
      queryCount > prev.current && queryCount > 0 && queryCount % 10 === 0;
    prev.current = queryCount;
    if (!crossed) return;
    setNod(true);
    const id = setTimeout(() => setNod(false), 4200);
    return () => clearTimeout(id);
  }, [queryCount]);

  return (
    <>
      <div ref={inkRef} className="ink-veil" aria-hidden />
      <AnimatePresence>
        {nod && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 220, damping: 22 }}
            className="pointer-events-none fixed bottom-24 left-1/2 z-50 -translate-x-1/2"
          >
            <div className="flex items-center gap-3 rounded-full border border-hairline bg-surface-2/90 py-2 pl-2.5 pr-4 shadow-xl backdrop-blur-md">
              <BrandMark engine={engine} thinking size={30} />
              <div className="leading-tight">
                <div className="tape text-[13px] text-ink">
                  {queryCount} analyses in
                </div>
                <div className="text-[11px] text-ink-dim">
                  The octopus has read a lot of ledger.
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
