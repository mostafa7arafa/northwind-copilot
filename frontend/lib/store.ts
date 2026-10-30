import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  ApiError,
  conversationsApi,
  datasetsApi,
  fetchModels,
  fetchPreferences,
  savePreferences,
  streamChat,
} from "./api";
import type {
  Engine,
  ModelRegistry,
  Provider,
  SavedTurn,
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

function detachConversation(session: Session, pendingTurnId?: string): Session {
  return {
    ...session,
    conversationId: undefined,
    turnCount: undefined,
    turns: session.turns.map((turn) => turn.id === pendingTurnId
      ? turn : { ...turn, browserOnly: true }),
  };
}

function restoreTurn(saved: SavedTurn, cached?: Turn): Turn {
  return {
    id: cached?.id ?? saved.id,
    serverTurnId: saved.id,
    question: saved.question,
    answer: saved.answer,
    provider: saved.provider,
    engine: saved.provider === "ollama" ? "local" : "cloud",
    model: saved.model,
    queries: saved.queries,
    charts: saved.charts.map((option) => ({ option, inferred: false })),
    insights: saved.insights ?? undefined,
    error: saved.error ?? undefined,
    stages: Object.fromEntries(STAGES.map((stage) => [stage, "done"])) as Turn["stages"],
    running: false,
    collapsed: cached?.collapsed ?? false,
    feedback: saved.feedback === undefined ? cached?.feedback : saved.feedback ?? undefined,
  };
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
  // The selected data source; each session tracks its own saved conversation.
  activeDatasetId: string | null;
  historyLoading: boolean;
  historyError: string;

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
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  toggleTurn: (turnId: string) => void;
  pinTurn: (turnId: string | null) => void;
  ask: (question: string) => Promise<void>;
  sendFeedback: (turnId: string, vote: "up" | "down") => Promise<void>;
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
      historyLoading: false,
      historyError: "",

      init: async () => {
        const initial = get();
        if (!initial.sessions.some((s) => s.id === initial.currentId)) {
          const sessions = initial.sessions.length ? initial.sessions : [newSession()];
          set({ sessions, currentId: sessions[0].id });
        }
        const datasetsReady = datasetsApi.list().then((datasets) => {
          const available = new Set(datasets.map((d) => d.id));
          set({
            activeDatasetId: available.has(get().activeDatasetId ?? "")
              ? get().activeDatasetId : null,
            sessions: get().sessions.map((s) => s.datasetId && !available.has(s.datasetId)
              ? { ...s, datasetId: null } : s),
          });
        });
        // These are independent: a model service failure must not hide history.
        await Promise.allSettled([
          (async () => {
            const registry = await fetchModels();
            set({ registry });
            const s = get();
            if (s.engine === "local" && registry.local.available) {
              if (!s.model) set({ provider: "ollama", model: registry.local.models[0]?.id ?? "" });
              return;
            }
            const cloud =
              (s.engine === "cloud" && registry.cloud.find((c) => c.provider === s.provider)) ||
              registry.cloud.find((c) => !c.needs_key) || registry.cloud[0];
            if (cloud) set({
              engine: "cloud",
              provider: cloud.provider,
              model: s.engine === "cloud" && s.provider === cloud.provider && s.model
                ? s.model : cloud.models[0]?.id ?? "",
            });
          })(),
          fetchPreferences().then((preferences) => set({ preferences })),
          datasetsReady,
          (async () => {
            set({ historyLoading: true, historyError: "" });
            try {
              const listedIds = new Set(get().sessions.map((s) => s.conversationId).filter(Boolean));
              const conversations = await conversationsApi.list();
              // Validate cached data sources before selecting a legacy session.
              await datasetsReady.catch(() => {});
              const existing = get().sessions;
              const saved = conversations.map((c) => {
                const cached = existing.find((s) => s.conversationId === c.id);
                return {
                  ...cached,
                  id: cached?.id ?? c.id,
                  title: c.title,
                  conversationId: c.id,
                  datasetId: c.dataset_id,
                  turnCount: c.turn_count,
                  turns: cached?.turns ?? [],
                  createdAt: cached?.createdAt ?? Date.now(),
                };
              });
              // Retain browser-only history, including stale hosted sessions,
              // but detach IDs the personal server does not recognize.
              const local = existing.filter((s) => !saved.some((c) => c.id === s.id))
                .map((s) => s.conversationId && listedIds.has(s.conversationId)
                  ? detachConversation(s) : s);
              set({ sessions: [...saved, ...local] });
              await get().selectSession(get().currentId);
            } catch {
              set({ historyError: "Couldn't load saved analyses. Your browser history is still available." });
            } finally {
              set({ historyLoading: false });
            }
          })(),
        ]);
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
      // A conversation belongs to one data source; don't relabel old turns.
      setActiveDataset: (id) => {
        if (id === get().activeDatasetId) return;
        set({ activeDatasetId: id });
        get().createSession();
      },

      createSession: () => {
        const s = { ...newSession(), datasetId: get().activeDatasetId };
        set({
          sessions: [s, ...get().sessions].slice(0, MAX_SESSIONS),
          currentId: s.id,
          pinnedTurnId: null,
          historyLoading: false,
          historyError: "",
        });
      },
      selectSession: async (id) => {
        const session = get().sessions.find((s) => s.id === id);
        if (!session) return;
        set({
          currentId: id,
          pinnedTurnId: null,
          activeDatasetId: session.datasetId ?? null,
          historyError: "",
          historyLoading: !!session.conversationId,
        });
        if (!session.conversationId) return;
        try {
          const detail = await conversationsApi.get(session.conversationId);
          // Don't overwrite a turn that began streaming while the request ran.
          set({
            sessions: get().sessions.map((s) => {
              if (s.id !== id || s.turns.some((t) => t.running)) return s;
              // A recovered legacy session can contain browser-only turns.
              // Restoring its new server history must not discard those.
              const matches = (cached: Turn, saved: SavedTurn) =>
                cached.id === saved.id || cached.serverTurnId === saved.id;
              const unmatched = s.turns.filter((t) =>
                !detail.turns.some((saved) => matches(t, saved))
              );
              const turns = [
                ...unmatched.filter((t) => t.browserOnly),
                ...detail.turns.map((t) => restoreTurn(t,
                  s.turns.find((cached) => matches(cached, t))
                )),
                // An interrupted request may still be saving on the server.
                ...unmatched.filter((t) => !t.browserOnly),
              ];
              return {
                ...s,
                title: detail.title,
                datasetId: detail.dataset_id,
                turnCount: turns.length,
                turns,
              };
            }),
          });
          if (get().currentId === id) set({ activeDatasetId: detail.dataset_id });
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            set({
              sessions: get().sessions.map((s) => s.id === id
                ? detachConversation(s) : s),
            });
          } else if (get().currentId === id) {
            set({ historyError: "Couldn't load this saved analysis. Try selecting it again." });
          }
        } finally {
          if (get().currentId === id) set({ historyLoading: false });
        }
      },

      deleteSession: async (id) => {
        const session = get().sessions.find((s) => s.id === id);
        if (session?.conversationId) {
          try {
            await conversationsApi.remove(session.conversationId);
          } catch (err) {
            if (!(err instanceof ApiError && err.status === 404)) {
              set({ historyError: "Couldn't delete the saved analysis. Try again." });
              return;
            }
          }
        }
        const remaining = get().sessions.filter((s) => s.id !== id);
        const sessions = remaining.length ? remaining : [{ ...newSession(), datasetId: get().activeDatasetId }];
        set({ sessions, pinnedTurnId: null });
        if (get().currentId === id) await get().selectSession(sessions[0].id);
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
        if (!trimmed || get().historyLoading) return;
        const { currentId, provider, model, engine, keys, kbHint, activeDatasetId } = get();

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
                  turnCount: (s.turnCount ?? s.turns.length) + 1,
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

        const source = get().sessions.find((s) => s.id === currentId)!;
        const request = async (conversationId = source.conversationId) => {
          await streamChat({
            messages: history,
            sessionId: currentId,
            turnId: turn.id,
            provider,
            model,
            apiKey,
            datasetId: activeDatasetId ?? undefined,
            conversationId,
            onEvent: (e) => {
              switch (e.type) {
                case "engine":
                  patch({ engine: e.engine, provider: e.provider, model: e.model });
                  break;
                case "conversation":
                  // Learn (or confirm) which server conversation this maps to.
                  set({
                    sessions: get().sessions.map((s) => s.id === currentId
                      ? { ...s, conversationId: e.id, datasetId: activeDatasetId }
                      : s),
                  });
                  break;
                case "turn":
                  // The server-persisted turn id — needed to attach feedback.
                  patch({ serverTurnId: e.id });
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
        };
        try {
          try {
            await request();
          } catch (err) {
            // A deleted/stale conversation should not strand browser history.
            if (!(err instanceof ApiError && err.status === 404 && source.conversationId)) throw err;
            set({ sessions: get().sessions.map((s) => s.id === currentId
              ? detachConversation(s, turn.id) : s) });
            await request("");
          }
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

      sendFeedback: async (turnId, vote) => {
        const { currentId, sessions } = get();
        const session = sessions.find((s) => s.id === currentId);
        const conversationId = session?.conversationId;
        const turn = session?.turns.find((t) => t.id === turnId);
        if (!turn?.serverTurnId || !conversationId) return;
        const prev = turn.feedback;
        // Optimistic: reflect the vote immediately; roll back on failure.
        const apply = (feedback: "up" | "down" | undefined) =>
          set({
            sessions: get().sessions.map((s) =>
              s.id !== currentId
                ? s
                : {
                    ...s,
                    turns: s.turns.map((t) =>
                      t.id === turnId ? { ...t, feedback } : t
                    ),
                  }
            ),
          });
        apply(vote);
        try {
          await conversationsApi.feedback(conversationId, turn.serverTurnId, vote);
        } catch {
          apply(prev);
        }
      },
    }),
    {
      name: "trading-desk",
      // NB: `keys` (provider API keys) are deliberately NOT persisted. Keeping
      // them in localStorage exposes them to any XSS or shared-machine user;
      // they live in memory only and can be re-entered each browser session.
      merge: (saved, current) => {
        // Ignore obsolete account state and any keys from older app versions.
        const data = saved as Partial<State> | undefined;
        const fields = [
          "engine", "provider", "model", "sessions", "currentId", "sidebarOpen",
          "artifactWidth", "kbHint", "queryCount", "activeDatasetId",
        ] as const;
        const restored = Object.fromEntries(
          fields.filter((key) => data?.[key] !== undefined)
            .map((key) => [key, data![key]])
        );
        return {
          ...current,
          ...restored,
          // A previous tab may have closed during a stream.
          sessions: (data?.sessions ?? current.sessions).map((session) => ({
            ...session,
            datasetId: session.datasetId !== undefined ? session.datasetId
              : session.id === data?.currentId ? data.activeDatasetId ?? null : undefined,
            turns: session.turns.map((turn) => ({
              ...turn,
              browserOnly: turn.browserOnly || !session.conversationId,
              running: false,
            })),
          })),
        };
      },
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
      }),
    }
  )
);

export { STAGES };
