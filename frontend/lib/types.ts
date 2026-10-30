// Shared domain types for the Trading Desk frontend.

export type Provider = "ollama" | "openai" | "openrouter";
export type Engine = "local" | "cloud";

export type StageId =
  | "understand"
  | "sql"
  | "execute"
  | "results"
  | "chart"
  | "insights";

export type StageStatus = "idle" | "active" | "done";

export interface ModelOption {
  id: string;
  label: string;
  note?: string;
}

export interface ModelRegistry {
  local: { provider: "ollama"; available: boolean; models: ModelOption[] };
  cloud: {
    provider: Provider;
    label: string;
    needs_key: boolean;
    models: ModelOption[];
  }[];
}

export interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
  truncated?: boolean;
}

// A single streamed event from the backend pipeline (SSE `data:` payloads).
// `seq` orders multi-artifact turns: each executed query gets its own sql +
// table pair, and a capable cloud model may draw several charts.
export type ChatEvent =
  | { type: "engine"; engine: Engine; provider: Provider; model: string }
  | { type: "conversation"; id: string }
  | { type: "turn"; id: string }
  | { type: "stage"; stage: StageId; status: "active" | "done" }
  | { type: "sql"; sql: string; seq?: number }
  | ({ type: "table"; seq?: number } & TableData)
  | { type: "chart"; option: Record<string, unknown>; inferred: boolean; seq?: number }
  | { type: "insights"; text: string; bullets: string[] }
  | { type: "final"; text: string }
  | { type: "error"; message: string; detail?: string }
  | { type: "done" };

/** One executed query and (once it arrives) its result table. */
export interface QueryArtifact {
  sql: string;
  table?: TableData;
}

export interface ChartArtifact {
  option: Record<string, unknown>;
  inferred: boolean;
}

export interface Turn {
  id: string;
  question: string;
  engine?: Engine;
  provider?: Provider;
  model?: string;
  stages: Record<StageId, StageStatus>;
  /** All executed queries with their tables, in execution order. */
  queries?: QueryArtifact[];
  /** All charts for the turn (cloud models may draw several). */
  charts?: ChartArtifact[];
  // Legacy single-artifact fields — still written (latest wins) and read as a
  // fallback so sessions persisted before multi-artifact support still render.
  sql?: string;
  table?: TableData;
  chart?: Record<string, unknown>;
  chartInferred?: boolean;
  insights?: { text: string; bullets: string[] };
  answer?: string;
  error?: { message: string; detail?: string };
  running: boolean;
  collapsed: boolean;
  /** The server-persisted turn id (from the `turn` SSE event);
   * required to attach feedback. */
  serverTurnId?: string;
  /** History retained from a browser-only or detached legacy conversation. */
  browserOnly?: boolean;
  /** The user's thumbs vote on this turn, if any. */
  feedback?: "up" | "down";
}

/** A turn's query artifacts, falling back to pre-multi-artifact fields. */
export function turnQueries(t: Turn): QueryArtifact[] {
  if (t.queries?.length) return t.queries;
  if (t.sql || t.table) return [{ sql: t.sql ?? "", table: t.table }];
  return [];
}

/** A turn's charts, falling back to pre-multi-artifact fields. */
export function turnCharts(t: Turn): ChartArtifact[] {
  if (t.charts?.length) return t.charts;
  if (t.chart) return [{ option: t.chart, inferred: !!t.chartInferred }];
  return [];
}

export interface Session {
  id: string;
  title: string;
  turns: Turn[];
  createdAt: number;
  conversationId?: string;
  datasetId?: string | null;
  turnCount?: number;
}

export type DatasetStatus = "processing" | "ready" | "failed";

export interface DatasetMeta {
  id: string;
  name: string;
  source_type: "csv" | "xlsx" | "sqlite";
  status: DatasetStatus;
  row_count: number;
  table_count: number;
  schema_summary: string;
  business_context: string;
  error: string;
}

export interface ConversationMeta {
  id: string;
  title: string;
  dataset_id: string | null;
  turn_count: number;
}

/** Saved artifacts returned by the conversation detail endpoint. */
export interface SavedTurn {
  id: string;
  question: string;
  answer: string;
  queries: QueryArtifact[];
  charts: Record<string, unknown>[];
  insights: Turn["insights"] | null;
  error: Turn["error"] | null;
  model: string;
  provider: Provider;
  /** Absent on older servers; null explicitly means unrated. */
  feedback?: "up" | "down" | null;
}

export interface ConversationDetail extends ConversationMeta {
  turns: SavedTurn[];
}
