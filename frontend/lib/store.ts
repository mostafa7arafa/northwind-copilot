import { create } from "zustand";
import { persist } from "zustand/middleware";
import { fetchModels, fetchPreferences, savePreferences, streamChat } from "./api";
import type {
  Engine,
  ModelRegistry,
  Provider,
  Session,
  StageId,
  TableData,
  Turn,
} from "./types";
import { turnQueries } from "./types";

const STAGES: StageId[] = [
  "understand",
  "sql",
  "execute",
  "results",
  "chart",
  "insights",
];

const idleStages = () =>
  Object.fromEntries(STAGES.map((s) => [s, "idle"])) as Turn["stages"];

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2, 10);

// Cap retained sessions so localStorage can't grow without bound. Each session
// can hold several turns with up to 500 result rows apiece.
const MAX_SESSIONS = 50;

function newSession(): Session {
  return { id: uid(), title: "New analysis", turns: [], createdAt: Date.now() };
}

// How many prior turns of history to replay, per engine. Cloud models have room
// for a richer window; local models have a tight context, so keep it short and
// let the server-side trim do the rest.
const HISTORY_WINDOW = { cloud: 5, local: 2 } as const;

/** Format a completed turn's result table as a compact few-row recap. */
function compactTable(table: TableData): string {
  const head = table.columns.join(" | ");
  const rows = table.rows
    .slice(0, 3)
    .map((r) => r.map((c) => (c === null ? "" : String(c))).join(" | "));
  const more =
    table.rows.length > 3 ? `\n… (${table.rows.length} rows total)` : "";
  return `Result (${table.rows.length} rows):\n${head}\n${rows.join("\n")}${more}`;
}

/**
 * Build the assistant-side memory for one prior turn.
 *
 * Cloud engines get a curated recap — the prose answer plus the exact SQL and a
 * few result rows — so follow-ups like "break that down by month" have a real
 * anchor. Local engines get prose only, to stay within their tight context.
 */
function turnMemory(t: Turn, engine: Engine): string {
  if (engine === "local") return t.answer ?? "";
  const parts: string[] = [];
  if (t.answer) parts.push(t.answer);
  // A complex turn may have run several queries; recap the first few so
  // follow-ups can anchor on any of them.
  for (const q of turnQueries(t).slice(0, 3)) {
    if (q.sql) parts.push("SQL used:\n```sql\n" + q.sql + "\n```");
    if (q.table && q.table.rows.length) parts.push(compactTable(q.table));
  }
  return parts.join("\n\n");
}

interface Keys {
  openai: string;
  openrouter: string;
}

interface State {
  // engine dashboard
  engine: Engine;
  provider: Provider;
  model: string;
  keys: Keys;
  // data
  registry: ModelRegistry | null;
  preferences: string;
  // sessions
  sessions: Session[];
  currentId: string;
  // ui
  sidebarOpen: boolean;
  artifactWidth: number; // right-docked workspace width, drag-resizable
  settingsOpen: boolean;
  pinnedTurnId: string | null;
  kbHint: boolean; // radar toggle: nudge the agent to consult the knowledge base
  queryCount: number; // completed analyses — drives the milestone easter egg
  // Hosted mode: the uploaded dataset to query, and the server-owned
  // conversation this session maps to (learned from the `conversation` event).
  activeDatasetId: string | null;
  conversationId: string | null;

  // actions
  init: () => Promise<void>;
  setEngine: (engine: Engine) => void;
  setProvider: (provider: Provider) => void;
  setModel: (model: string) => void;
  setKey: (provider: "openai" | "openrouter", value: string) => void;
  setPreferences: (text: string) => Promise<void>;
  toggleSidebar: () => void;
  setArtifactWidth: (width: number) => void;
  openSettings: (open: boolean) => void;
  toggleKbHint: () => void;
  setActiveDataset: (id: string | null) => void;
  createSession: () => void;
  selectSession: (id: string) => void;
  deleteSession: (id: string) => void;
  toggleTurn: (turnId: string) => void;
  pinTurn: (turnId: string | null) => void;
  ask: (question: string) => Promise<void>;
}

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      engine: "local",
      provider: "ollama",
      model: "",
      keys: { openai: "", openrouter: "" },
      registry: null,
      preferences: "",
      sessions: [newSession()],
      currentId: "",
      sidebarOpen: true,
      artifactWidth: 460,
      settingsOpen: false,
      pinnedTurnId: null,
      kbHint: false,
      queryCount: 0,
      activeDatasetId: null,
      conversationId: null,

      init: async () => {
        if (!get().currentId) set({ currentId: get().sessions[0].id });
        try {
          const [registry, preferences] = await Promise.all([
            fetchModels(),
            fetchPreferences(),
          ]);
          set({ registry, preferences });
          const s = get();
          // If the local engine isn't available (always the case in the hosted
          // product — no Ollama), force the cloud engine so requests don't go
          // to a non-existent local daemon.
          const localUsable = registry.local.available && s.engine === "local";
          // Prefer a cloud provider the server already has a key for (no BYOK
          // needed), e.g. our OpenRouter key in the hosted product.
          const cloud =
            registry.cloud.find((c) => !c.needs_key) ?? registry.cloud[0];
          if (!localUsable && cloud?.models[0]) {
            const cloudDefault = cloud.models[0].id;
            // Coming from the local engine, a persisted model id is an Ollama
            // model — reset to a cloud model so requests don't fail.
            const keepModel = s.engine === "cloud" && s.model;
            set({
              engine: "cloud",
              provider: cloud.provider,
              model: keepModel || cloudDefault,
            });
          } else if (!s.model && registry.local.models[0]) {
            set({ provider: "ollama", model: registry.local.models[0].id });
          }
        } catch {
          /* backend offline; UI still renders */
        }
      },

      setEngine: (engine) => {
        const { registry } = get();
        if (engine === "local") {
          const first = registry?.local.models[0]?.id ?? "";
          set({ engine, provider: "ollama", model: first });
        } else {
          const p = registry?.cloud[0];
          set({
            engine,
            provider: p?.provider ?? "openai",
            model: p?.models[0]?.id ?? "",
          });
        }
      },
      setProvider: (provider) => {
        const { registry } = get();
        const p = registry?.cloud.find((c) => c.provider === provider);
        set({ provider, model: p?.models[0]?.id ?? get().model });
      },
      setModel: (model) => set({ model }),
      setKey: (provider, value) =>
        set({ keys: { ...get().keys, [provider]: value } }),
      setPreferences: async (text) => {
        const saved = await savePreferences(text);
        set({ preferences: saved });
      },
      toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
      setArtifactWidth: (width) =>
        set({ artifactWidth: Math.max(380, Math.min(width, 900)) }),
      openSettings: (open) => set({ settingsOpen: open }),
      toggleKbHint: () => set({ kbHint: !get().kbHint }),
      // Switching dataset starts a fresh server-side conversation.
      setActiveDataset: (id) => set({ activeDatasetId: id, conversationId: null }),

      createSession: () => {
        const s = newSession();
        set({
          sessions: [s, ...get().sessions].slice(0, MAX_SESSIONS),
          currentId: s.id,
          pinnedTurnId: null,
          conversationId: null, // a new session is a new server conversation
        });
      },
      selectSession: (id) =>
        set({ currentId: id, pinnedTurnId: null, conversationId: null }),

      deleteSession: (id) => {
        const remaining = get().sessions.filter((s) => s.id !== id);
        // Never leave the app with zero sessions — seed a fresh one.
        const sessions = remaining.length ? remaining : [newSession()];
        // If we deleted the active session, fall back to the newest remaining.
        const currentId =
          get().currentId === id ? sessions[0].id : get().currentId;
        set({ sessions, currentId, pinnedTurnId: null });
      },

      toggleTurn: (turnId) =>
        set({
          sessions: get().sessions.map((s) =>
            s.id !== get().currentId
              ? s
              : {
                  ...s,
                  turns: s.turns.map((t) =>
                    t.id === turnId ? { ...t, collapsed: !t.collapsed } : t
                  ),
                }
          ),
        }),
      pinTurn: (turnId) => set({ pinnedTurnId: turnId }),

      ask: async (question) => {
        const trimmed = question.trim();
        if (!trimmed) return;
        const { currentId, provider, model, engine, keys, kbHint } = get();

        const turn: Turn = {
          id: uid(),
          question: trimmed,
          stages: idleStages(),
          running: true,
          collapsed: false,
        };

        // Insert the turn and title the session from its first question.
        set({
          pinnedTurnId: turn.id,
          sessions: get().sessions.map((s) =>
            s.id !== currentId
              ? s
              : {
                  ...s,
                  title:
                    s.turns.length === 0
                      ? trimmed.slice(0, 42)
                      : s.title,
                  turns: [...s.turns, turn],
                }
          ),
        });

        // patchFn computes the update from the turn's current state, so
        // handlers can append to the queries/charts arrays as events stream in.
        const patchFn = (fn: (t: Turn) => Partial<Turn>) =>
          set({
            sessions: get().sessions.map((s) =>
              s.id !== currentId
                ? s
                : {
                    ...s,
                    turns: s.turns.map((t) =>
                      t.id === turn.id ? { ...t, ...fn(t) } : t
                    ),
                  }
            ),
          });
        const patch = (p: Partial<Turn>) => patchFn(() => p);

        const setStage = (stage: StageId, status: "active" | "done") =>
          set({
            sessions: get().sessions.map((s) =>
              s.id !== currentId
                ? s
                : {
                    ...s,
                    turns: s.turns.map((t) =>
                      t.id === turn.id
                        ? { ...t, stages: { ...t.stages, [stage]: status } }
                        : t
                    ),
                  }
            ),
          });

        // History = a window of prior turns in this session, plus this Q. Cloud
        // engines get a curated recap (SQL + result rows) so follow-ups have an
        // anchor; local engines get a short prose-only window to fit their
        // tight context (see turnMemory / HISTORY_WINDOW).
        const session = get().sessions.find((s) => s.id === currentId)!;
        const windowSize =
          engine === "local" ? HISTORY_WINDOW.local : HISTORY_WINDOW.cloud;
        const history = session.turns
          .filter((t) => t.id !== turn.id)
          .slice(-windowSize)
          .flatMap((t) => {
            const memory = turnMemory(t, engine);
            return [
              { role: "user", content: t.question },
              ...(memory ? [{ role: "assistant", content: memory }] : []),
            ];
          });
        // Radar toggle on → gently invite the agent to use its knowledge-base
        // tool for this turn. The displayed question (turn.question) stays clean.
        const askContent = kbHint
          ? `${trimmed}\n\n(You may consult the product knowledge base with search_docs if it helps.)`
          : trimmed;
        history.push({ role: "user", content: askContent });

        const apiKey =
          provider === "openai"
            ? keys.openai
            : provider === "openrouter"
            ? keys.openrouter
            : undefined;

        try {
          await streamChat({
            messages: history,
            sessionId: currentId,
            provider,
            model,
            apiKey,
            // Hosted mode: query the active dataset and continue the server-side
            // conversation. Ignored by the POC backend.
            datasetId: get().activeDatasetId ?? undefined,
            conversationId: get().conversationId ?? undefined,
            onEvent: (e) => {
              switch (e.type) {
                case "engine":
                  patch({ engine: e.engine, provider: e.provider, model: e.model });
                  break;
                case "conversation":
                  // Learn (or confirm) which server conversation this maps to.
                  set({ conversationId: e.id });
                  break;
                case "stage":
                  setStage(e.stage, e.status);
                  break;
                case "sql":
                  patchFn((t) => ({
                    sql: e.sql,
                    queries: [...(t.queries ?? []), { sql: e.sql }],
                  }));
                  break;
                case "table": {
                  const data = {
                    columns: e.columns,
                    rows: e.rows,
                    truncated: e.truncated,
                  };
                  patchFn((t) => {
                    // Pair the table with its query by seq; fall back to the
                    // first query still missing a table.
                    const queries = [...(t.queries ?? [])];
                    const i =
                      typeof e.seq === "number" && queries[e.seq]
                        ? e.seq
                        : queries.findIndex((q) => !q.table);
                    if (i >= 0 && queries[i]) {
                      queries[i] = { ...queries[i], table: data };
                    } else {
                      queries.push({ sql: "", table: data });
                    }
                    return { table: data, queries };
                  });
                  break;
                }
                case "chart":
                  patchFn((t) => ({
                    chart: e.option,
                    chartInferred: e.inferred,
                    charts: [
                      ...(t.charts ?? []),
                      { option: e.option, inferred: e.inferred },
                    ],
                  }));
                  break;
                case "insights":
                  patch({ insights: { text: e.text, bullets: e.bullets } });
                  break;
                case "final":
                  patch({ answer: e.text });
                  set({ queryCount: get().queryCount + 1 });
                  break;
                case "error":
                  patch({ error: { message: e.message, detail: e.detail } });
                  break;
              }
            },
          });
        } catch (err) {
          patch({
            error: {
              message: "The stream was interrupted.",
              detail: err instanceof Error ? err.message : String(err),
            },
          });
        } finally {
          patch({ running: false });
        }
      },
    }),
    {
      name: "trading-desk",
      // NB: `keys` (provider API keys) are deliberately NOT persisted. Keeping
      // them in localStorage exposes them to any XSS or shared-machine user;
      // they live in memory only and are re-entered per session until the
      // backend stores them per-user server-side.
      partialize: (s) => ({
        engine: s.engine,
        provider: s.provider,
        model: s.model,
        sessions: s.sessions,
        currentId: s.currentId,
        sidebarOpen: s.sidebarOpen,
        artifactWidth: s.artifactWidth,
        kbHint: s.kbHint,
        queryCount: s.queryCount,
        activeDatasetId: s.activeDatasetId,
        conversationId: s.conversationId,
      }),
    }
  )
);

export { STAGES };
