"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { octopusInner } from "@/lib/octopus";
import type { Engine } from "@/lib/types";
import { cn } from "@/lib/cn";

/**
 * The Northwind octopus. Steel on the local engine, electric on cloud (it carries
 * the same tint as the QueryTrace rail). At rest it breathes; while `thinking` it
 * gathers itself, then ripples continuously. Motion is dropped under
 * prefers-reduced-motion. See lib/octopus.ts for the arm kinematics.
 */
export function BrandMark({
  engine = "local",
  thinking = false,
  size = 24,
  className,
  title = "Northwind octopus",
}: {
  engine?: Engine;
  thinking?: boolean;
  size?: number;
  className?: string;
  title?: string;
}) {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduce(mq.matches);
    const on = () => setReduce(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // Play the "gather" one-shot each time it starts thinking.
  const [gather, setGather] = useState(false);
  const wasThinking = useRef(thinking);
  useEffect(() => {
    if (thinking && !wasThinking.current) {
      setGather(true);
      const id = setTimeout(() => setGather(false), 640);
      wasThinking.current = thinking;
      return () => clearTimeout(id);
    }
    wasThinking.current = thinking;
  }, [thinking]);

  const inner = useMemo(() => octopusInner(thinking, reduce), [thinking, reduce]);

  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      role="img"
      aria-label={title}
      data-engine={engine}
      className={cn("bm", thinking && "is-thinking", gather && "is-gather", className)}
      dangerouslySetInnerHTML={{ __html: `<title>${title}</title>${inner}` }}
    />
  );
}
