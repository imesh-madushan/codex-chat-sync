import { useEffect, useMemo, useRef, useState } from "react";
import { call } from "./api";
import { Empty, Modal, chatTitle } from "./ui";

const norm = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();

export default function ChatsTab({ busy, run, note, data, archived, setArchived, reload, settings, goImport }) {
  const { threads, projects } = data;
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [selected, setSelected] = useState(() => new Set()); // survives filtering
  const [active, setActive] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const [done, setDone] = useState(null);
  const serial = useRef(0);

  const projectName = useMemo(() => Object.fromEntries(projects.map((p) => [p.id, p.name || p.id])), [projects]);
  const folders = useMemo(() => [...new Set(threads.map((t) => t.cwd))].sort(), [threads]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return threads.filter((t) => {
      if (q && !(chatTitle(t) + " " + t.cwd).toLowerCase().includes(q)) return false;
      if (scope === "unassigned") return !t.projectId;
      if (scope.startsWith("project:")) return t.projectId === scope.slice(8);
      if (scope.startsWith("folder:")) return norm(t.cwd) === norm(scope.slice(7));
      return true;
    });
  }, [threads, query, scope]);

  // Drop selections for chats that no longer exist after a refresh.
  useEffect(() => {
    const ids = new Set(threads.map((t) => t.id));
    setSelected((s) => new Set([...s].filter((id) => ids.has(id))));
  }, [threads]);

  const toggle = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const selectVisible = () => setSelected((s) => new Set([...s, ...visible.map((t) => t.id)]));
  const allVisibleSelected = visible.length > 0 && visible.every((t) => selected.has(t.id));

  // Debounced conversation preview for the highlighted chat.
  useEffect(() => {
    if (!active) return undefined;
    const mine = ++serial.current;
    setPreview({ loading: true });
    const id = setTimeout(async () => {
      try {
        const details = await call("preview", active.id);
        if (mine === serial.current) setPreview(details);
      } catch (e) {
        if (mine === serial.current) setPreview({ error: e.message });
      }
    }, 250);
    return () => clearTimeout(id);
  }, [active]);

  const doExport = async () => {
    setConfirm(false);
    const result = await run("Exporting selected conversations…", () => call("export_chats", [...selected]));
    if (result) { note("Export ready: " + result.path, "ok"); setDone(result.path); reload(); }
  };

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>Chats on this device</h1>
          <p className="sub">Pick the conversations to carry to your other computer, then export one bundle.</p>
        </div>
        <button className="btn ghost" disabled={busy} onClick={() => reload()}>Refresh</button>
      </header>

      <div className="toolbar">
        <input className="input grow" placeholder="Search titles or folders…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="input" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="all">All chats</option>
          <option value="unassigned">Unassigned chats</option>
          {projects.map((p) => <option key={p.id} value={"project:" + p.id}>Project: {p.name || p.id}</option>)}
          {folders.map((f) => <option key={f} value={"folder:" + f}>Folder: {f}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={archived} disabled={busy} onChange={(e) => setArchived(e.target.checked)} /> Archived</label>
      </div>

      <div className="split">
        <div className="panel list">
          {visible.length === 0 ? <Empty>{threads.length ? "No chats match your filter." : "No chats loaded yet."}</Empty> : visible.map((t) => (
            <div key={t.id} className={"row" + (active && active.id === t.id ? " row-active" : "")} onClick={() => setActive(t)}>
              <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} onClick={(e) => e.stopPropagation()} aria-label={"Select " + chatTitle(t)} />
              <div className="row-main">
                <div className="row-title">{chatTitle(t)}</div>
                <div className="row-sub">{projectName[t.projectId] || "Unassigned"} · {t.cwd}</div>
              </div>
            </div>
          ))}
        </div>

        <aside className="panel detail">
          <h4>Conversation preview</h4>
          {!active && <p className="muted">Click a chat to see its details.</p>}
          {active && (
            <>
              <div className="detail-title">{chatTitle(active)}</div>
              <div className="kv"><span>Folder</span><code>{active.cwd}</code></div>
              {preview && preview.loading && <p className="muted">Loading completed history…</p>}
              {preview && preview.error && <p className="muted">Preview unavailable: {preview.error}</p>}
              {preview && preview.last_message && (
                <>
                  <div className="kv"><span>Turns</span>{preview.completed} completed / {preview.turn_count} total</div>
                  <div className="kv col"><span>Last assistant message</span><p className="quote">{preview.last_message}</p></div>
                </>
              )}
            </>
          )}
        </aside>
      </div>

      <div className="actionbar">
        <button className="btn" disabled={busy || !visible.length || allVisibleSelected} onClick={selectVisible}>Select visible</button>
        <button className="btn ghost" disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear</button>
        <span className="grow counter">{selected.size} selected · {visible.length} visible</span>
        <button className="btn primary" disabled={busy || !selected.size} onClick={() => setConfirm(true)}>Export selected</button>
      </div>

      {confirm && (
        <Modal title="Export conversations" onClose={() => setConfirm(false)}
          actions={<><button className="btn ghost" onClick={() => setConfirm(false)}>Back</button><button className="btn primary" onClick={doExport}>Export</button></>}>
          <p>Export <b>{selected.size}</b> conversation{selected.size === 1 ? "" : "s"} into one immutable bundle.</p>
          <div className="kv col"><span>Exchange folder</span><code>{settings && settings.values.exchange_dir}</code></div>
          <p className="muted">Bundles contain the full chat text and tool output. Keep the exchange folder private.</p>
        </Modal>
      )}

      {done && (
        <Modal title="Export complete" onClose={() => setDone(null)}
          actions={<><button className="btn ghost" onClick={() => setDone(null)}>Close</button><button className="btn primary" onClick={() => { setDone(null); goImport(); }}>Go to Import</button></>}>
          <p>Your bundle is saved in the exchange folder. Let your file-sync service carry it to the other computer, then import it there.</p>
          <code className="block">{done}</code>
        </Modal>
      )}
    </section>
  );
}
