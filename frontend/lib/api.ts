import type { ChatEvent, ModelRegistry, Provider } from "./types";

/** Fetch the local + cloud model registry. */
export async function fetchModels(): Promise<ModelRegistry> {
  const res = await fetch("/api/models", { cache: "no-store" });
  if (!res.ok) throw new Error("Couldn't load models");
  return res.json();
}

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
    }),
    signal: args.signal,
  });

  if (!res.ok || !res.body) {
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
