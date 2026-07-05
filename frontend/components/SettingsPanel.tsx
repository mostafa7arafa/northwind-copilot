"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, KeyRound, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";

const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";

/** Settings drawer: analyst preferences (appended to the system prompt) and
 * per-provider API keys (kept in this browser only). */
export function SettingsPanel() {
  const { settingsOpen, openSettings, preferences, setPreferences, keys, setKey } =
    useStore();
  const [draft, setDraft] = useState(preferences);
  const [saved, setSaved] = useState(false);

  useEffect(() => setDraft(preferences), [preferences, settingsOpen]);

  const save = async () => {
    await setPreferences(draft);
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  return (
    <AnimatePresence>
      {settingsOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => openSettings(false)}
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 34 }}
            className="fixed right-0 top-0 z-50 flex h-full w-[420px] max-w-[92vw] flex-col border-l border-hairline bg-surface"
          >
            <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
              <h2 className="tape text-[15px] text-ink">Settings</h2>
              <button
                onClick={() => openSettings(false)}
                className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex-1 space-y-8 overflow-auto p-5">
              {/* preferences */}
              <section>
                <div className="mb-1 flex items-center gap-2">
                  <Sparkles size={14} className="text-electric" />
                  <h3 className="text-[13.5px] font-medium text-ink">Analyst preferences</h3>
                </div>
                <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">
                  Free text added to the system prompt on every question. Tell the
                  analyst how you want answers — currency, rounding, favourite
                  metrics, tables to prefer.
                </p>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={6}
                  placeholder={
                    "e.g. Always show revenue in USD, rounded to whole dollars. Prefer gross margin over raw revenue. Label months as short names."
                  }
                  className="w-full resize-none rounded-lg border border-hairline bg-bg p-3 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-faint focus:border-electric/50"
                />
                <button
                  onClick={save}
                  className="mt-2 flex items-center gap-1.5 rounded-lg bg-electric px-3 py-1.5 text-[12.5px] font-medium text-bg transition hover:brightness-110"
                >
                  {saved ? <Check size={13} /> : null}
                  {saved ? "Saved" : "Save preferences"}
                </button>
              </section>

              {/* keys */}
              <section>
                <div className="mb-1 flex items-center gap-2">
                  <KeyRound size={14} className="text-warn" />
                  <h3 className="text-[13.5px] font-medium text-ink">Provider keys</h3>
                </div>
                {HOSTED ? (
                  <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">
                    <span className="text-electric">
                      Your free trial includes cloud model calls on our API keys
                    </span>{" "}
                    — you don&apos;t need to add anything to start asking
                    questions. Add your own OpenAI or OpenRouter key below to
                    run on your own account instead. Keys are kept only in this
                    browser and sent with your requests — never persisted on the
                    server.
                  </p>
                ) : (
                  <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">
                    Required for cloud engines. Stored only in this browser and
                    sent with your requests — never persisted on the server.
                  </p>
                )}
                <div className="space-y-3">
                  {(
                    [
                      { id: "openai", label: "OpenAI API key", ph: "sk-…" },
                      { id: "openrouter", label: "OpenRouter API key", ph: "sk-or-…" },
                    ] as const
                  ).map(({ id, label, ph }) => (
                    <label key={id} className="block">
                      <span className="eyebrow mb-1 block">{label}</span>
                      <input
                        type="password"
                        value={keys[id]}
                        onChange={(e) => setKey(id, e.target.value)}
                        placeholder={ph}
                        className="tape w-full rounded-lg border border-hairline bg-bg px-3 py-2 text-[12.5px] text-ink outline-none placeholder:text-ink-faint focus:border-electric/50"
                      />
                    </label>
                  ))}
                </div>
              </section>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
