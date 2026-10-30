const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { createRequire } = require("node:module");
const { test } = require("node:test");
const { transpileModule, ModuleKind, ScriptTarget } = require("typescript");

// Exercise the real TypeScript store/API without adding a browser test runtime.
function setup(persisted = {}) {
  const storage = new Map([
    ["trading-desk", JSON.stringify({ state: persisted, version: 0 })],
    ["unrelated", "keep me"],
  ]);
  const localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  };
  global.window = { localStorage };
  const requests = [];
  let respond = () => { throw new Error("Unexpected API request"); };
  global.fetch = async (url, options = {}) => {
    const request = {
      url,
      method: options.method ?? "GET",
      body: typeof options.body === "string" ? JSON.parse(options.body) : options.body,
    };
    requests.push(request);
    return respond(request);
  };
  const cache = new Map();
  function load(file) {
    const filename = join(__dirname, "..", "lib", `${file}.ts`);
    if (cache.has(filename)) return cache.get(filename);
    const output = transpileModule(readFileSync(filename, "utf8"), {
      compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2020 },
    }).outputText;
    const module = { exports: {} };
    cache.set(filename, module.exports);
    const nativeRequire = createRequire(filename);
    new Function("require", "module", "exports", output)(
      (name) => name.startsWith("./") ? load(name.slice(2)) : nativeRequire(name),
      module,
      module.exports
    );
    return module.exports;
  }
  return {
    store: load("store").useStore,
    api: load("api"),
    storage,
    requests,
    respond: (fn) => { respond = fn; },
  };
}

const json = (data, status = 200) => Response.json(data, { status });
const sse = (...events) => new Response(
  events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
  { headers: { "Content-Type": "text/event-stream" } }
);
const registry = {
  local: { available: true, provider: "ollama", models: [{ id: "llama3.2", label: "Local" }] },
  cloud: [
    { provider: "openai", needs_key: true, models: [{ id: "gpt-test", label: "OpenAI" }] },
    { provider: "openrouter", needs_key: false, models: [{ id: "router-test", label: "OpenRouter" }] },
  ],
};
const stages = Object.fromEntries(["understand", "sql", "execute", "results", "chart", "insights"].map((stage) => [stage, "done"]));
const legacySession = {
  id: "browser-session", title: "Retained history", createdAt: 1,
  turns: [{ id: "browser-turn", question: "Original question", answer: "Original answer", stages, running: true, collapsed: false }],
};
const saved = { id: "saved", title: "Saved analysis", dataset_id: null, turn_count: 1 };
const detail = {
  ...saved,
  turns: [{
    id: "server-turn", question: "Count", answer: "Two", provider: "ollama", model: "llama3.2",
    queries: [{ sql: "SELECT 2", table: { columns: ["n"], rows: [[2]] } }],
    charts: [{ series: [{ data: [2] }] }], insights: { text: "Insight", bullets: [] }, error: null,
  }],
};
function startup(request, conversations = [], datasets = []) {
  switch (request.url) {
    case "/api/models": return json(registry);
    case "/api/preferences": return json({ preferences: "Use USD" });
    case "/api/datasets": return json(datasets);
    case "/api/conversations": return json(conversations);
    default: throw new Error(`Unexpected startup request ${request.url}`);
  }
}

test("store: legacy history survives startup; obsolete account IDs/keys cannot hydrate", async () => {
  const env = setup({
    sessions: [legacySession], currentId: legacySession.id,
    activeDatasetId: "old-hosted-dataset", conversationId: "old-hosted-conversation",
    keys: { openai: "old-secret", openrouter: "old-secret" }, usage: { plan: "trial" },
  });
  env.respond((request) => startup(request));
  await env.store.getState().init();
  const state = env.store.getState();
  assert.equal(state.sessions[0].turns[0].answer, "Original answer");
  assert.equal(state.sessions[0].turns[0].running, false);
  assert.equal(state.activeDatasetId, null);
  assert.equal(state.conversationId, undefined);
  assert.equal(state.usage, undefined);
  assert.deepEqual(state.keys, { openai: "", openrouter: "" });
  state.setKey("openai", "new-secret");
  assert.equal(env.store.getState().keys.openai, "new-secret");
  assert.doesNotMatch(env.storage.get("trading-desk"), /new-secret|old-secret|old-hosted-conversation/);
  assert.equal(env.storage.get("unrelated"), "keep me");
  assert.deepEqual(env.requests.map((r) => r.url).sort(), ["/api/conversations", "/api/datasets", "/api/models", "/api/preferences"]);
});

test("store: startup restores saved sample artifacts and feedback uses server IDs", async () => {
  const env = setup();
  env.respond((request) => request.url === "/api/conversations/saved" ? json(detail) : startup(request, [saved]));
  await env.store.getState().init();
  await env.store.getState().selectSession("saved");
  const session = env.store.getState().sessions.find((s) => s.id === "saved");
  assert.equal(session.conversationId, "saved");
  assert.equal(env.store.getState().activeDatasetId, null);
  assert.deepEqual(session.turns[0].queries, detail.turns[0].queries);
  assert.deepEqual(session.turns[0].charts[0].option, detail.turns[0].charts[0]);
  assert.equal(session.turns[0].serverTurnId, "server-turn");
  assert.equal(session.turns[0].running, false);
  env.respond((request) => {
    assert.equal(request.url, "/api/conversations/saved/turns/server-turn/feedback");
    assert.deepEqual(request.body, { vote: "up" });
    return json({ vote: "up", golden_example: false });
  });
  await env.store.getState().sendFeedback("server-turn", "up");
  assert.equal(env.store.getState().sessions.find((s) => s.id === "saved").turns[0].feedback, "up");
});

test("store: sample and uploaded chats retain streamed artifacts, IDs, and per-session datasets", async () => {
  const env = setup();
  env.respond(startup);
  await env.store.getState().init();
  const sampleId = env.store.getState().currentId;
  let count = 0;
  env.respond((request) => {
    assert.equal(request.url, "/api/chat");
    count += 1;
    assert.equal(request.body.dataset_id, count === 1 ? null : "upload");
    assert.equal(request.body.conversation_id, null);
    const current = env.store.getState();
    assert.equal(request.body.turn_id, current.sessions.find((s) => s.id === current.currentId).turns.at(-1).id);
    return sse(
      { type: "conversation", id: `conversation-${count}` },
      { type: "engine", engine: "local", provider: "ollama", model: "llama3.2" },
      { type: "sql", sql: "SELECT 2", seq: 0 },
      { type: "table", columns: ["n"], rows: [[2]], seq: 0 },
      { type: "chart", option: { series: [] }, inferred: true },
      { type: "insights", text: "Insight", bullets: [] },
      { type: "final", text: "Two" },
      { type: "turn", id: `turn-${count}` }, { type: "done" }
    );
  });
  await env.store.getState().ask("Sample count");
  env.store.getState().setActiveDataset("upload");
  await env.store.getState().ask("Upload count");
  const state = env.store.getState();
  assert.equal(state.sessions.find((s) => s.id === sampleId).conversationId, "conversation-1");
  const uploaded = state.sessions.find((s) => s.id === state.currentId);
  assert.equal(uploaded.datasetId, "upload");
  assert.equal(uploaded.conversationId, "conversation-2");
  assert.equal(uploaded.turns[0].serverTurnId, "turn-2");
  assert.equal(uploaded.turns[0].queries[0].table.rows[0][0], 2);
  assert.equal(uploaded.turns[0].charts[0].inferred, true);
  assert.equal(uploaded.turns[0].running, false);
  env.respond(() => json({ ...detail, id: "conversation-1" }));
  await state.selectSession(sampleId);
  assert.equal(env.store.getState().activeDatasetId, null);
});

test("store: stale conversation detail and chat 404 recover without clearing browser turns", async () => {
  const env = setup({ sessions: [{ ...legacySession, conversationId: "deleted" }], currentId: legacySession.id });
  env.respond(() => json({ detail: "Not found" }, 404));
  await env.store.getState().selectSession(legacySession.id);
  assert.equal(env.store.getState().sessions[0].conversationId, undefined);
  assert.equal(env.store.getState().sessions[0].turns[0].answer, "Original answer");
  env.store.setState({ sessions: [{ ...env.store.getState().sessions[0], conversationId: "deleted" }] });
  let attempts = 0;
  let retryTurnId;
  env.respond((request) => {
    attempts += 1;
    assert.equal(request.body.turn_id, env.store.getState().sessions[0].turns.at(-1).id);
    if (retryTurnId) assert.equal(request.body.turn_id, retryTurnId);
    retryTurnId = request.body.turn_id;
    if (attempts === 1) {
      assert.equal(request.body.conversation_id, "deleted");
      return json({ detail: "Not found" }, 404);
    }
    assert.equal(request.body.conversation_id, null);
    return sse({ type: "conversation", id: "replacement" }, { type: "final", text: "Recovered" }, { type: "turn", id: "new-turn" });
  });
  await env.store.getState().ask("Follow up");
  const session = env.store.getState().sessions[0];
  assert.equal(attempts, 2);
  assert.equal(session.conversationId, "replacement");
  assert.equal(session.turns.length, 2);
  assert.equal(session.turns[0].answer, "Original answer");
  assert.equal(session.turns[1].answer, "Recovered");
  env.respond(() => json({
    ...detail, id: "replacement",
    turns: [{ ...detail.turns[0], id: "new-turn", question: "Follow up", answer: "Recovered" }],
  }));
  await env.store.getState().selectSession(legacySession.id);
  assert.deepEqual(env.store.getState().sessions[0].turns.map((t) => t.answer), ["Original answer", "Recovered"]);
});

test("store: deletion failures retain history; successful deletion removes saved conversation", async () => {
  const env = setup({ sessions: [{ ...legacySession, conversationId: "saved" }], currentId: legacySession.id });
  env.respond(() => json({ detail: "Unavailable" }, 503));
  await env.store.getState().deleteSession(legacySession.id);
  assert.equal(env.store.getState().sessions[0].id, legacySession.id);
  assert.match(env.store.getState().historyError, /Couldn't delete/);
  env.respond((request) => {
    assert.equal(request.url, "/api/conversations/saved");
    assert.equal(request.method, "DELETE");
    return new Response(null, { status: 204 });
  });
  await env.store.getState().deleteSession(legacySession.id);
  assert.equal(env.store.getState().sessions.length, 1);
  assert.notEqual(env.store.getState().currentId, legacySession.id);
});

test("store: model startup respects persisted cloud provider/model and server environment keys", async () => {
  const env = setup({ engine: "cloud", provider: "openrouter", model: "custom/router-model" });
  env.respond(startup);
  await env.store.getState().init();
  assert.equal(env.store.getState().provider, "openrouter");
  assert.equal(env.store.getState().model, "custom/router-model");
  env.store.getState().setEngine("local");
  assert.equal(env.store.getState().provider, "ollama");
  assert.equal(env.store.getState().model, "llama3.2");
  env.store.getState().setEngine("cloud");
  env.store.getState().setProvider("openai");
  env.respond((request) => {
    assert.equal(request.body.provider, "openai");
    assert.equal(request.body.api_key, null);
    return sse({ type: "final", text: "Environment key" });
  });
  await env.store.getState().ask("Use configured key");
});

test("store: history/model startup failures are independent and leave browser history usable", async () => {
  const env = setup({ sessions: [legacySession], currentId: legacySession.id });
  env.respond((request) => request.url === "/api/conversations" ? json({ detail: "Unavailable" }, 503) : startup(request));
  await env.store.getState().init();
  assert.ok(env.store.getState().registry);
  assert.equal(env.store.getState().preferences, "Use USD");
  assert.equal(env.store.getState().historyLoading, false);
  assert.match(env.store.getState().historyError, /Couldn't load saved/);
  assert.equal(env.store.getState().sessions[0].turns[0].answer, "Original answer");
});

test("api: upload, append, query, context, preferences, and rename retain existing contracts", async () => {
  const env = setup();
  env.respond(() => json({}));
  const file = new File(["a\n1"], "rows.csv", { type: "text/csv" });
  await env.api.datasetsApi.upload(file, "Rows");
  await env.api.datasetsApi.addFile("dataset", file);
  await env.api.datasetsApi.query("dataset", "SELECT * FROM rows");
  await env.api.datasetsApi.updateContext("dataset", "Amounts are USD");
  await env.api.savePreferences("Use USD");
  await env.api.conversationsApi.rename("saved", "Renamed");
  const [upload, append, query, context, preferences, rename] = env.requests;
  assert.equal(upload.url, "/api/datasets");
  assert.equal(upload.body.get("name"), "Rows");
  assert.equal(upload.body.get("file").name, "rows.csv");
  assert.equal(append.url, "/api/datasets/dataset/files");
  assert.equal(query.url, "/api/datasets/dataset/query");
  assert.deepEqual(query.body, { sql: "SELECT * FROM rows" });
  assert.equal(context.method, "PUT");
  assert.deepEqual(context.body, { business_context: "Amounts are USD" });
  assert.equal(preferences.url, "/api/preferences");
  assert.equal(rename.method, "PATCH");
  assert.deepEqual(rename.body, { title: "Renamed" });
});

test("store: legacy selected dataset is retained when valid and detached when deleted", async () => {
  const env = setup({ sessions: [legacySession], currentId: legacySession.id, activeDatasetId: "upload" });
  env.respond((request) => startup(request, [], [{ id: "upload" }]));
  await env.store.getState().init();
  assert.equal(env.store.getState().activeDatasetId, "upload");
  assert.equal(env.store.getState().sessions[0].datasetId, "upload");
  env.respond((request) => startup(request));
  await env.store.getState().init();
  assert.equal(env.store.getState().activeDatasetId, null);
  assert.equal(env.store.getState().sessions[0].datasetId, null);
  assert.equal(env.store.getState().sessions[0].turns[0].answer, "Original answer");
});

test("store: a late stream cannot change the data source of a newly selected session", async () => {
  const env = setup();
  env.respond(startup);
  await env.store.getState().init();
  const sampleId = env.store.getState().currentId;
  let finish;
  env.respond(() => new Promise((resolve) => { finish = resolve; }));
  const pending = env.store.getState().ask("Sample question");
  env.store.getState().setActiveDataset("upload");
  const uploadId = env.store.getState().currentId;
  finish(sse({ type: "conversation", id: "sample-saved" }, { type: "final", text: "Answer" }));
  await pending;
  const state = env.store.getState();
  assert.equal(state.currentId, uploadId);
  assert.equal(state.activeDatasetId, "upload");
  assert.equal(state.sessions.find((s) => s.id === sampleId).datasetId, null);
  assert.equal(state.sessions.find((s) => s.id === sampleId).conversationId, "sample-saved");
  assert.equal(state.sessions.find((s) => s.id === uploadId).conversationId, undefined);
});

test("store: disconnect/reload reconciles stable turn IDs in server order, including delayed saves", async () => {
  const env = setup({ sessions: [{ ...legacySession, conversationId: "deleted" }], currentId: legacySession.id });
  env.respond(() => json({ detail: "Not found" }, 404));
  await env.store.getState().selectSession(legacySession.id);
  const persistedTurns = [];
  let count = 0;
  env.respond((request) => {
    count += 1;
    persistedTurns.push({ ...detail.turns[0], id: request.body.turn_id, question: `Q${count}`, answer: `A${count}` });
    if (count === 1) return sse(
      { type: "conversation", id: "recovered" },
      { type: "final", text: "A1" },
      { type: "turn", id: request.body.turn_id }
    );
    // The answer reached the browser, but persistence's final turn event did not.
    let sent = false;
    return new Response(new ReadableStream({
      pull(controller) {
        if (sent) return controller.error(new Error("Disconnected before turn event"));
        sent = true;
        controller.enqueue(new TextEncoder().encode('data: {"type":"final","text":"A2"}\n\n'));
      },
    }));
  });
  await env.store.getState().ask("Q1");
  await env.store.getState().ask("Q2");
  const beforeReload = env.store.getState().sessions[0];
  const q2 = beforeReload.turns.at(-1);
  assert.equal(q2.id, persistedTurns[1].id);
  assert.equal(q2.serverTurnId, undefined);
  assert.match(q2.error.message, /interrupted/);
  // Feedback must wait for the persistence event, not just the client ID.
  const requestCount = env.requests.length;
  await env.store.getState().sendFeedback(q2.id, "up");
  assert.equal(env.requests.length, requestCount);

  const reloaded = setup(JSON.parse(env.storage.get("trading-desk")).state);
  let serverTurns = persistedTurns.slice(0, 1);
  reloaded.respond(() => json({ ...detail, id: "recovered", turns: serverTurns }));
  await reloaded.store.getState().selectSession(legacySession.id);
  assert.deepEqual(reloaded.store.getState().sessions[0].turns.map((t) => t.question), ["Original question", "Q1", "Q2"]);
  // A later detail response includes the server's completed Q2. No second copy.
  serverTurns = persistedTurns;
  await reloaded.store.getState().selectSession(legacySession.id);
  const restored = reloaded.store.getState().sessions[0].turns;
  assert.deepEqual(restored.map((t) => t.question), ["Original question", "Q1", "Q2"]);
  assert.equal(restored[0].browserOnly, true);
  assert.equal(restored[2].id, q2.id);
  assert.equal(restored[2].serverTurnId, q2.id);
  assert.equal(restored[2].browserOnly, undefined);
  assert.equal(restored[2].error, undefined);
  assert.equal(restored[2].running, false);
  assert.equal(reloaded.storage.get("unrelated"), "keep me");
});

test("store: saved history follows server order rather than cached order and matches either turn ID", async () => {
  const env = setup({
    sessions: [{ ...legacySession, conversationId: "saved", turns: [
      { ...legacySession.turns[0], id: "q2", question: "Q2" },
      { ...legacySession.turns[0], id: "local-q1", serverTurnId: "q1", question: "Q1" },
    ] }], currentId: legacySession.id,
  });
  env.respond(() => json({ ...detail, turns: [
    { ...detail.turns[0], id: "q1", question: "Q1" },
    { ...detail.turns[0], id: "q2", question: "Q2" },
  ] }));
  await env.store.getState().selectSession(legacySession.id);
  assert.deepEqual(env.store.getState().sessions[0].turns.map((t) => t.id), ["local-q1", "q2"]);
});

test("store: pending startup list cannot detach a conversation learned by a new analysis", async () => {
  const env = setup();
  let finishList;
  env.respond((request) => request.url === "/api/conversations"
    ? new Promise((resolve) => { finishList = resolve; }) : startup(request));
  const initializing = env.store.getState().init();
  env.store.getState().createSession();
  const id = env.store.getState().currentId;
  let turnId;
  env.respond((request) => {
    assert.equal(request.url, "/api/chat");
    turnId = request.body.turn_id;
    return sse({ type: "conversation", id: "new-saved" }, { type: "turn", id: turnId });
  });
  await env.store.getState().ask("First question");
  env.respond((request) => {
    assert.equal(request.url, "/api/conversations/new-saved");
    return json({ ...detail, id: "new-saved", turns: [{ ...detail.turns[0], id: turnId }] });
  });
  finishList(json([]));
  await initializing;
  assert.equal(env.store.getState().sessions.find((s) => s.id === id).conversationId, "new-saved");
  env.respond((request) => {
    assert.equal(request.url, "/api/chat");
    assert.equal(request.body.conversation_id, "new-saved");
    return sse({ type: "turn", id: request.body.turn_id });
  });
  await env.store.getState().ask("Next question");
  assert.equal(env.store.getState().sessions.find((s) => s.id === id).conversationId, "new-saved");
});

test("store: saved feedback restores on a fresh cache and server null clears a cached vote", async () => {
  const env = setup();
  let feedback = "up";
  env.respond((request) => request.url === "/api/conversations/saved"
    ? json({ ...detail, turns: [{ ...detail.turns[0], feedback }] }) : startup(request, [saved]));
  await env.store.getState().init();
  await env.store.getState().selectSession("saved");
  const restoredFeedback = () => env.store.getState().sessions.find((s) => s.id === "saved").turns[0].feedback;
  assert.equal(restoredFeedback(), "up");
  feedback = "down";
  await env.store.getState().selectSession("saved");
  assert.equal(restoredFeedback(), "down");
  // Older server responses lacking feedback retain compatible browser votes.
  feedback = undefined;
  await env.store.getState().selectSession("saved");
  assert.equal(restoredFeedback(), "down");
  feedback = null;
  await env.store.getState().selectSession("saved");
  assert.equal(restoredFeedback(), undefined);
});
