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
export type ChatEvent =
  | { type: "engine"; engine: Engine; provider: Provider; model: string }
  | { type: "stage"; stage: StageId; status: "active" | "done" }
  | { type: "sql"; sql: string }
  | ({ type: "table" } & TableData)
  | { type: "chart"; option: Record<string, unknown>; inferred: boolean }
  | { type: "insights"; text: string; bullets: string[] }
  | { type: "final"; text: string }
  | { type: "error"; message: string; detail?: string }
  | { type: "done" };

export interface Turn {
  id: string;
  question: string;
  engine?: Engine;
  provider?: Provider;
  model?: string;
  stages: Record<StageId, StageStatus>;
  sql?: string;
  table?: TableData;
  chart?: Record<string, unknown>;
  chartInferred?: boolean;
  insights?: { text: string; bullets: string[] };
  answer?: string;
  error?: { message: string; detail?: string };
  running: boolean;
  collapsed: boolean;
}

export interface Session {
  id: string;
  title: string;
  turns: Turn[];
  createdAt: number;
}
