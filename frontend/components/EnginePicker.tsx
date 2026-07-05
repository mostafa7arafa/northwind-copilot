"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Cloud,
  Cpu,
  KeyRound,
  Sparkles,
} from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useStore } from "@/lib/store";
import type { ModelOption, Provider } from "@/lib/types";
import { cn } from "@/lib/cn";

const MENU_WIDTH = 288;

// The hosted product is cloud-only (no Ollama daemon on the server), so the
// Local/Cloud engine switch is hidden and inference runs on our metered keys.
const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";

/** The engine dashboard: switch between the local and cloud brains, choose a
 * provider, and pick (or type) the exact model. The whole control is tinted by
 * the active engine — steel for local, electric for cloud. */
export function EnginePicker() {
  const {
    engine,
    provider,
    model,
    registry,
    keys,
    setEngine,
    setProvider,
    setModel,
    openSettings,
  } = useStore();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const cloud = engine === "cloud";
  const tint = cloud ? "var(--color-electric)" : "var(--color-steel)";

  const cloudProviders = registry?.cloud ?? [];
  const currentModels: ModelOption[] =
    engine === "local"
      ? registry?.local.models ?? []
      : cloudProviders.find((c) => c.provider === provider)?.models ?? [];

  const localMissing = engine === "local" && !registry?.local.available;
  const providerNeedsKey =
    cloudProviders.find((c) => c.provider === provider)?.needs_key ?? true;
  const keyMissing =
    cloud &&
    provider !== "ollama" &&
    providerNeedsKey &&
    !keys[provider as "openai" | "openrouter"];

  // Position the portalled menu under the trigger, right-aligned and clamped.
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8));
    setPos({ top: r.bottom + 8, left });
  }, [open]);

  const choose = (id: string) => {
    const next = id.trim();
    if (!next) return;
    setModel(next);
    setOpen(false);
    setTyped("");
  };

  // Hosted: the server's key covers this provider and the user hasn't added
  // their own — surface that the free trial includes model calls.
  const trialCovered =
    HOSTED &&
    cloud &&
    !providerNeedsKey &&
    !keys[provider as "openai" | "openrouter"];

  return (
    <div className="flex items-center gap-2">
      {/* engine segmented control — hidden in the hosted product (cloud-only) */}
      {!HOSTED && (
      <div className="flex items-center rounded-lg border border-hairline bg-bg p-0.5">
        {(
          [
            { id: "local", label: "Local", Icon: Cpu },
            { id: "cloud", label: "Cloud", Icon: Cloud },
          ] as const
        ).map(({ id, label, Icon }) => {
          const on = engine === id;
          return (
            <button
              key={id}
              onClick={() => setEngine(id)}
              className={cn(
                "relative flex h-8 items-center gap-1.5 rounded-md px-3 text-[12.5px] transition-colors",
                on ? "text-ink" : "text-ink-dim hover:text-ink"
              )}
            >
              {on && (
                <motion.span
                  layoutId="engine-pill"
                  className="absolute inset-0 rounded-md"
                  style={{ background: `${id === "cloud" ? "#4f8cff" : "#6b8fb8"}22` }}
                  transition={{ type: "spring", stiffness: 320, damping: 30 }}
                />
              )}
              <Icon
                size={13}
                className="relative"
                style={{ color: on ? (id === "cloud" ? "#4f8cff" : "#6b8fb8") : undefined }}
              />
              <span className="relative">{label}</span>
            </button>
          );
        })}
      </div>
      )}

      {/* cloud provider tabs */}
      {cloud && (
        <div className="flex items-center rounded-lg border border-hairline bg-bg p-0.5">
          {cloudProviders.map((c) => (
            <button
              key={c.provider}
              onClick={() => setProvider(c.provider as Provider)}
              className={cn(
                "h-8 rounded-md px-2.5 text-[12px] transition-colors",
                provider === c.provider
                  ? "bg-surface-2 text-ink"
                  : "text-ink-dim hover:text-ink"
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}

      {/* model picker trigger */}
      <button
        ref={triggerRef}
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 items-center gap-2 rounded-lg border border-hairline bg-surface px-3 text-[12.5px] text-ink transition-colors hover:border-hairline-strong"
      >
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: tint, boxShadow: `0 0 6px ${tint}` }}
        />
        <span className="tape max-w-[180px] truncate">{model || "Select model"}</span>
        <ChevronDown size={13} className="text-ink-dim" />
      </button>

      {/* menu — portalled to <body> so it escapes the header's blur stacking
          context and never hides behind page content */}
      {typeof document !== "undefined" &&
        createPortal(
          <AnimatePresence>
            {open && pos && (
              <>
                <div
                  className="fixed inset-0"
                  style={{ zIndex: 999 }}
                  onClick={() => setOpen(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  transition={{ duration: 0.14 }}
                  style={{ position: "fixed", top: pos.top, left: pos.left, width: MENU_WIDTH, zIndex: 1000 }}
                  className="overflow-hidden rounded-xl border border-hairline bg-surface-2 shadow-2xl"
                >
                  {/* type any model id — the primary path for newest models */}
                  <div className="border-b border-hairline p-2.5">
                    <div className="eyebrow mb-1.5">Type any model id</div>
                    <div className="flex items-center gap-1.5">
                      <input
                        autoFocus
                        value={typed}
                        onChange={(e) => setTyped(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") choose(typed);
                        }}
                        placeholder={
                          engine === "local" ? "e.g. llama3.2" : "e.g. gpt-5, o3, gpt-4.1"
                        }
                        className="tape min-w-0 flex-1 rounded-md border border-hairline bg-bg px-2.5 py-1.5 text-[12px] text-ink outline-none placeholder:text-ink-faint focus:border-electric/60"
                      />
                      <button
                        onClick={() => choose(typed)}
                        disabled={!typed.trim()}
                        title="Use this model"
                        className="flex h-[30px] items-center gap-1 rounded-md bg-electric px-2 text-[12px] font-medium text-bg transition enabled:hover:brightness-110 disabled:opacity-40"
                      >
                        Use <ArrowRight size={12} />
                      </button>
                    </div>
                  </div>

                  <div className="eyebrow px-3 py-2">
                    {engine === "local" ? "Installed local models" : "Suggested models"}
                  </div>
                  <div className="max-h-64 overflow-auto pb-1">
                    {localMissing && (
                      <p className="px-3 py-3 text-[12.5px] leading-relaxed text-ink-dim">
                        No local models found. Start Ollama and pull one (e.g.
                        <span className="tape"> ollama pull llama3.2</span>).
                      </p>
                    )}
                    {currentModels.map((m) => (
                      <button
                        key={m.id}
                        onClick={() => choose(m.id)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-surface"
                      >
                        <span className="min-w-0">
                          <span className="tape block truncate text-[12.5px] text-ink">
                            {m.label}
                          </span>
                          {m.note && (
                            <span className="text-[11px] text-ink-faint">{m.note}</span>
                          )}
                        </span>
                        {model === m.id && <Check size={14} style={{ color: tint }} />}
                      </button>
                    ))}
                  </div>
                </motion.div>
              </>
            )}
          </AnimatePresence>,
          document.body
        )}

      {keyMissing && (
        <button
          onClick={() => openSettings(true)}
          className="flex h-8 items-center gap-1.5 rounded-lg border border-warn/40 bg-warn/5 px-2.5 text-[12px] text-warn transition-colors hover:bg-warn/10"
        >
          <KeyRound size={12} /> Add key
        </button>
      )}

      {trialCovered && (
        <button
          type="button"
          onClick={() => openSettings(true)}
          className="flex h-8 items-center gap-1.5 rounded-lg border border-electric/30 bg-electric/5 px-2.5 text-[12px] text-electric transition-colors hover:bg-electric/10"
          title="Model calls are included in your free trial (our API key). Click to add your own key instead."
        >
          <Sparkles size={12} /> Free trial · included
        </button>
      )}
    </div>
  );
}
