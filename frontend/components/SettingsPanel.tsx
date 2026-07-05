"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, KeyRound, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, keysApi } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { ApiKeyMeta } from "@/lib/types";

const HOSTED = process.env.NEXT_PUBLIC_HOSTED_MODE === "true";

const PROVIDERS = [
  { id: "openai", label: "OpenAI API key", ph: "sk-…" },
  { id: "openrouter", label: "OpenRouter API key", ph: "sk-or-…" },
] as const;

/** Hosted mode: one provider's server-side BYOK key — set/replace/clear.
 * The key is write-only: after saving, only its last4 is ever shown. */
function ServerKeyRow({
  id,
  label,
  ph,
  meta,
  onChange,
}: {
  id: "openai" | "openrouter";
  label: string;
  ph: string;
  meta: ApiKeyMeta | undefined;
  onChange: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    setError("");
    try {
      await keysApi.set(id, draft.trim());
      setDraft("");
      onChange();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save the key."
      );
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setError("");
    try {
      await keysApi.remove(id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-hairline bg-bg p-3">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {meta && (
          <span className="flex items-center gap-1.5 text-[11.5px] text-electric">
            <ShieldCheck size={12} />
            <span className="tape">•••• {meta.last4}</span>
          </span>
        )}
      </div>
      {meta ? (
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11.5px] text-ink-faint">
            Stored encrypted · set {new Date(meta.set_at).toLocaleDateString()}
          </span>
          <button
            type="button"
            onClick={clear}
            disabled={busy}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-ink-dim transition-colors hover:bg-surface-2 hover:text-warn"
          >
            <Trash2 size={11} /> Clear
          </button>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          <input
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={ph}
            className="tape w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-[12.5px] text-ink outline-none placeholder:text-ink-faint focus:border-electric/50"
          />
          <button
            type="button"
            onClick={save}
            disabled={busy || !draft.trim()}
            className="shrink-0 rounded-lg bg-electric px-3 py-1.5 text-[12px] font-medium text-bg transition hover:brightness-110 disabled:opacity-40"
          >
            Save
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-[11.5px] text-warn">{error}</p>}
    </div>
  );
}

/** Settings drawer: analyst preferences (appended to the system prompt) and
 * provider API keys — stored encrypted server-side in the hosted product,
 * kept in-browser only for the POC. */
export function SettingsPanel() {
  const { settingsOpen, openSettings, preferences, setPreferences, keys, setKey } =
    useStore();
  const refreshUsage = useStore((s) => s.refreshUsage);
  const [draft, setDraft] = useState(preferences);
  const [saved, setSaved] = useState(false);
  const [serverKeys, setServerKeys] = useState<ApiKeyMeta[]>([]);

  useEffect(() => setDraft(preferences), [preferences, settingsOpen]);

  const loadKeys = async () => {
    try {
      setServerKeys(await keysApi.list());
    } catch {
      /* panel still renders; rows just show as unset */
    }
  };

  useEffect(() => {
    if (HOSTED && settingsOpen) void loadKeys();
  }, [settingsOpen]);

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
                type="button"
                onClick={() => openSettings(false)}
                aria-label="Close settings"
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
                  <>
                    <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">
                      Add your own OpenAI or OpenRouter key to run unmetered on
                      your account (paid plans). Keys are encrypted at rest,
                      never shown again after saving, and never returned by the
                      API — without one, turns run on our key and use your
                      plan&apos;s credits.
                    </p>
                    <div className="space-y-3">
                      {PROVIDERS.map(({ id, label, ph }) => (
                        <ServerKeyRow
                          key={id}
                          id={id}
                          label={label}
                          ph={ph}
                          meta={serverKeys.find((k) => k.provider === id)}
                          onChange={() => {
                            void loadKeys();
                            void refreshUsage();
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">
                      Required for cloud engines. Stored only in this browser and
                      sent with your requests — never persisted on the server.
                    </p>
                    <div className="space-y-3">
                      {PROVIDERS.map(({ id, label, ph }) => (
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
                  </>
                )}
              </section>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
