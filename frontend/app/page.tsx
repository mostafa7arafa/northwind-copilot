"use client";

import { useEffect, useState } from "react";
import { ArtifactPanel } from "@/components/ArtifactPanel";
import { Composer } from "@/components/Composer";
import { Conversation } from "@/components/Conversation";
import { EasterEggs } from "@/components/EasterEggs";
import { Header } from "@/components/Header";
import { SettingsPanel } from "@/components/SettingsPanel";
import { Sidebar } from "@/components/Sidebar";
import { useStore } from "@/lib/store";

export default function Page() {
  const init = useStore((s) => s.init);
  const sessions = useStore((s) => s.sessions);
  const currentId = useStore((s) => s.currentId);
  const running =
    sessions.find((s) => s.id === currentId)?.turns.some((t) => t.running) ?? false;

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    init();
  }, [init]);

  // Gate on mount so the persisted (localStorage) store doesn't clash with the
  // server-rendered default state and trigger a hydration mismatch.
  if (!mounted) return <div className="h-screen w-screen bg-bg" />;

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-auto">
            <Conversation />
          </div>
          <ArtifactPanel />
        </main>
        <Composer busy={running} />
      </div>
      <SettingsPanel />
      <EasterEggs />
    </div>
  );
}
