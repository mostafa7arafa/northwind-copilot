"use client";

import { useEffect, useRef } from "react";
import { useStore } from "@/lib/store";
import { EmptyState } from "./EmptyState";
import { QueryTurn } from "./QueryTurn";

/** The scrolling thread of query turns, or the empty state on a fresh session. */
export function Conversation() {
  const { sessions, currentId, ask } = useStore();
  const session = sessions.find((s) => s.id === currentId);
  const endRef = useRef<HTMLDivElement>(null);
  const turns = session?.turns ?? [];
  const running = turns.some((t) => t.running);

  // Auto-scroll while the latest turn streams in.
  useEffect(() => {
    if (running) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [running, turns.length]);

  if (turns.length === 0) {
    return <EmptyState onPick={(q) => ask(q)} />;
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-2">
      {turns.map((t) => (
        <QueryTurn key={t.id} turn={t} />
      ))}
      <div ref={endRef} className="h-4" />
    </div>
  );
}
