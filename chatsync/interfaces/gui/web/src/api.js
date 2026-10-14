// Thin client for the Python bridge (window.pywebview.api).
// Outside pywebview (plain `npm run dev` in a browser) a small mock is used so the UI can be developed alone.

let ready;
function bridge() {
  if (ready) return ready;
  ready = new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
    // Not inside pywebview (browser dev): fall back to the mock after a short wait.
    setTimeout(() => { if (!(window.pywebview && window.pywebview.api)) resolve(mock); }, 600);
  });
  return ready;
}

export async function call(method, ...args) {
  const api = await bridge();
  const result = await api[method](...args);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

export const isMock = async () => (await bridge()) === mock;

// ---------------------------------------------------------------- mock data
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ok = (data) => ({ ok: true, data });
const threads = [
  { id: "t1", name: "Design the sync engine", cwd: "D:/Projects/sample-app", projectId: "p1" },
  { id: "t2", name: "Fix export checksum bug", cwd: "D:/Projects/sample-app", projectId: "p1" },
  { id: "t3", name: "Write README", cwd: "D:/Projects/notes", projectId: null },
];
const mock = {
  get_settings: async () => ok({ configured: true, settings_path: "~/.local/share/CodexChatSync/config.json",
    values: { device_name: "dev-laptop", codex_home: "~/.codex", codex_executable: "/usr/bin/codex",
              exchange_dir: "~/Sync/ChatBundles", state_dir: "~/.local/share/CodexChatSync/state" },
    mappings: {} }),
  save_settings: async () => ok({}),
  load_snapshot: async () => { await sleep(400); return ok({ threads, projects: [{ id: "p1", name: "sample-app" }],
    bundles: [{ path: "~/Sync/ChatBundles/chats-demo.chatbundle.zip", name: "chats-demo.chatbundle.zip" }],
    history: [{ operation: "a1b2c3d4e5f6", status: "committed", created_at: "2026-10-13T20:00:00", title: "Design the sync engine" }] }); },
  preview: async (id) => { await sleep(300); return ok({ turn_count: 10, completed: 10, last_message: "Mock preview for " + id }); },
  export_chats: async () => { await sleep(800); return ok({ path: "~/Sync/ChatBundles/chats-new.chatbundle.zip" }); },
  load_bundle: async (path) => { await sleep(400); return ok({ path, hash: "x", source_device: "office-pc", codex_version: "0.162.1",
    created_at: "2026-10-13T18:00:00Z",
    chats: [{ id: "t1", title: "Design the sync engine", cwd: "C:/Work/sample-app", turns: 10, project: "sample-app" },
            { id: "t3", title: "Write README", cwd: "C:/Work/notes", turns: 4, project: null }] }); },
  review_import: async (p, ids) => { await sleep(500); return ok(ids.map((id, i) => ({ node: id, title: id, action: ["new", "update", "branch", "same"][i % 4], destination: "D:/x" }))); },
  run_import: async (p, ids) => { await sleep(900); return ok(ids.map((id) => ({ node: id, title: id, action: "new", destination: "D:/x", thread_id: "0190-mock-" + id }))); },
  load_history: async () => ok([]),
  rollback: async () => ok([]),
  pick_folder: async () => ok("D:/Projects/picked"),
  pick_file: async () => ok("D:/picked/file"),
  busy: async () => false,
};
