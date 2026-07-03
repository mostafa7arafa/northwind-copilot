"use client";

import { PanelLeft, Settings2 } from "lucide-react";
import { useStore } from "@/lib/store";
import { EnginePicker } from "./EnginePicker";
import { BrandMark } from "./BrandMark";

/** Top bar: sidebar toggle, wordmark, the engine dashboard, and settings. */
export function Header() {
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  const openSettings = useStore((s) => s.openSettings);
  const engine = useStore((s) => s.engine);
  const running = useStore((s) =>
    s.sessions
      .find((sess) => sess.id === s.currentId)
      ?.turns.some((t) => t.running) ?? false
  );

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-hairline bg-bg/80 px-4 backdrop-blur-md">
      <div className="flex items-center gap-3">
        <button
          onClick={toggleSidebar}
          className="rounded-md p-2 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
          title="Toggle sidebar"
        >
          <PanelLeft size={17} />
        </button>
        <div className="flex items-center gap-2.5">
          <BrandMark engine={engine} thinking={running} size={26} />
          <div className="hidden items-baseline gap-2 sm:flex">
            <span className="tape text-[14px] font-medium text-ink">Trading Desk</span>
            <span className="eyebrow">Northwind</span>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <EnginePicker />
        <button
          onClick={() => openSettings(true)}
          className="rounded-md p-2 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
          title="Settings"
        >
          <Settings2 size={17} />
        </button>
      </div>
    </header>
  );
}
