"use client";

import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { useRef, useState } from "react";
import { useStore } from "@/lib/store";
import { BrandMark } from "./BrandMark";

const EXAMPLES = [
  "Top 5 products by revenue in 2017",
  "Which category earned the most gross margin?",
  "Products currently below their reorder level",
  "Beverage revenue by month across 2017",
  "Employees ranked by number of orders handled",
  "Average order value for orders that include seafood",
];

/** First-run canvas: a mono headline, a cursor-following glow, and real
 * Northwind starter questions the analyst can click to run. */
export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [glow, setGlow] = useState({ x: 0.5, y: 0.3, on: false });
  const engine = useStore((s) => s.engine);

  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        const r = ref.current!.getBoundingClientRect();
        setGlow({ x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, on: true });
      }}
      onMouseLeave={() => setGlow((g) => ({ ...g, on: false }))}
      className="relative mx-auto flex h-full max-w-2xl flex-col justify-center px-6"
    >
      {/* one deliberate flourish: a faint glow tracking the cursor */}
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-500"
        style={{
          opacity: glow.on ? 1 : 0.4,
          background: `radial-gradient(420px circle at ${glow.x * 100}% ${glow.y * 100}%, rgba(79,140,255,0.10), transparent 60%)`,
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 140, damping: 22 }}
        className="relative"
      >
        <BrandMark engine={engine} size={72} className="mb-5" />
        <div className="eyebrow mb-3">Northwind Trading Desk</div>
        <h1 className="tape text-[34px] font-medium leading-[1.1] text-ink">
          Ask the ledger
          <span className="text-ink-faint">.</span>
        </h1>
        <p className="mt-3 max-w-md text-[15px] leading-relaxed text-ink-dim">
          Plain-language questions become SQL, tables and charts — drawn live, step
          by step. Start with one of these, or type your own below.
        </p>

        <div className="mt-7 grid gap-2 sm:grid-cols-2">
          {EXAMPLES.map((q, i) => (
            <motion.button
              key={q}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.05 }}
              onClick={() => onPick(q)}
              className="card-lift group flex items-center justify-between gap-3 rounded-xl border border-hairline bg-surface px-3.5 py-3 text-left text-[13.5px] text-ink/90 hover:border-electric/40"
            >
              <span>{q}</span>
              <ArrowUpRight
                size={15}
                className="shrink-0 text-ink-faint transition-colors group-hover:text-electric"
              />
            </motion.button>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
