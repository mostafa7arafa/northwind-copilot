import type {
  ChatEvent,
  ConversationDetail,
  ConversationMeta,
  DatasetMeta,
  ModelRegistry,
  Provider,
  TableData,
} from "./types";

/** Thrown for non-2xx API responses, carrying the status and server detail. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function requireOk(res: Response): Promise<void> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, detail);
  }
}

async function json<T>(res: Response): Promise<T> {
  await requireOk(res);
  return res.json() as Promise<T>;
}

/** Fetch the local + cloud model registry. */
export async function fetchModels(): Promise<ModelRegistry> {
  const res = await fetch("/api/models", { cache: "no-store" });
  if (!res.ok) throw new Error("Couldn't load models");
  return res.json();
}

// --- Datasets ------------------------------------------------------------

export const datasetsApi = {
  async list(): Promise<DatasetMeta[]> {
    return json(await fetch("/api/datasets", { cache: "no-store" }));
  },
  async get(id: string): Promise<DatasetMeta> {
    return json(await fetch(`/api/datasets/${id}`, { cache: "no-store" }));
  },
  async upload(file: File, name: string): Promise<DatasetMeta> {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    return json(
      await fetch("/api/datasets", { method: "POST", body: form })
    );
  },
  async updateContext(id: string, businessContext: string): Promise<DatasetMeta> {
    return json(
      await fetch(`/api/datasets/${id}/context`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ business_context: businessContext }),
      })
    );
  },
  /** Add another file's tables to an existing dataset (multi-file datasets). */
  async addFile(id: string, file: File): Promise<DatasetMeta> {
    const form = new FormData();
    form.append("file", file);
    return json(
      await fetch(`/api/datasets/${id}/files`, {
        method: "POST",
        body: form,
      })
    );
  },
  /** Run a user-edited SELECT against a dataset (read-only, time-boxed). */
  async query(id: string, sql: string): Promise<TableData> {
    return json(
      await fetch(`/api/datasets/${id}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql }),
      })
    );
  },
  async remove(id: string): Promise<void> {
    await requireOk(await fetch(`/api/datasets/${id}`, { method: "DELETE" }));
  },
};

// --- Conversations -------------------------------------------------------

export const conversationsApi = {
  async list(): Promise<ConversationMeta[]> {
    return json(await fetch("/api/conversations", { cache: "no-store" }));
  },
  async get(id: string): Promise<ConversationDetail> {
    return json(
      await fetch(`/api/conversations/${id}`, { cache: "no-store" })
    );
  },
  async rename(id: string, title: string): Promise<ConversationMeta> {
    return json(
      await fetch(`/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      })
    );
  },
  async remove(id: string): Promise<void> {
    await requireOk(await fetch(`/api/conversations/${id}`, { method: "DELETE" }));
  },
  /** Thumbs-vote a turn; up on a dataset turn stores a golden example. */
  async feedback(
    conversationId: string,
    turnId: string,
    vote: "up" | "down"
  ): Promise<{ vote: string; golden_example: boolean }> {
    return json(
      await fetch(`/api/conversations/${conversationId}/turns/${turnId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vote }),
      })
    );
  },
};

/** Read saved analyst preferences. */
export async function fetchPreferences(): Promise<string> {
  const res = await fetch("/api/preferences", { cache: "no-store" });
  if (!res.ok) return "";
  return (await res.json()).preferences ?? "";
}

/** Save analyst preferences (appended to the system prompt server-side). */
export async function savePreferences(preferences: string): Promise<string> {
  const res = await fetch("/api/preferences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preferences }),
  });
  if (!res.ok) throw new Error("Couldn't save preferences");
  return (await res.json()).preferences ?? "";
}

export interface ChatArgs {
  messages: { role: string; content: string }[];
  sessionId: string;
  provider: Provider;
  model: string;
  apiKey?: string;
  /** The dataset to query and the saved conversation to append to. */
  datasetId?: string;
  conversationId?: string;
  signal?: AbortSignal;
  onEvent: (event: ChatEvent) => void;
}

/**
 * Stream one analyst turn. Reads the SSE body and calls `onEvent` for each
 * parsed pipeline event until the stream closes.
 */
export async function streamChat(args: ChatArgs): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: args.messages,
      session_id: args.sessionId,
      provider: args.provider,
      model: args.model,
      api_key: args.apiKey || null,
      dataset_id: args.datasetId || null,
      conversation_id: args.conversationId || null,
    }),
    signal: args.signal,
  });

  await requireOk(res);
  if (!res.body) {
    args.onEvent({
      type: "error",
      message: "The analyst service is unreachable.",
      detail: `HTTP ${res.status}`,
    });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        args.onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}
