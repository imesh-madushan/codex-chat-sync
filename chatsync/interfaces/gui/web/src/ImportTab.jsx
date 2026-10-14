import { useMemo, useState } from "react";
import { call } from "./api";
import { Badge, Empty, Modal, copyText } from "./ui";

export default function ImportTab({ busy, run, note, data, settings, setSettings, reload }) {
  const [path, setPath] = useState("");
  const [bundle, setBundle] = useState(null);      // {path, hash, chats, ...}
  const [loadedFrom, setLoadedFrom] = useState(""); // text that was loaded
  const [picked, setPicked] = useState(() => new Set());
  const [maps, setMaps] = useState({});              // source folder -> {dest, project}
  const [plans, setPlans] = useState(null);          // review result; null = must review again
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState(null);

  const saved = (settings && settings.mappings) || {};
  const chats = bundle ? bundle.chats : [];
  const sources = useMemo(() => [...new Set(chats.filter((c) => picked.has(c.id)).map((c) => c.cwd))], [chats, picked]);
  const stale = !bundle || path.trim() !== loadedFrom;

  const invalidate = () => setPlans(null);

  const load = async (target = path) => {
    const text = target.trim();
    if (!text) return;
    const info = await run("Validating bundle checksums and dependencies…", () => call("load_bundle", text));
    if (!info) return;
    setBundle(info);
    setLoadedFrom(text);
    setPicked(new Set());
    setPlans(null);
    setMaps(Object.fromEntries([...new Set(info.chats.map((c) => c.cwd))].map((src) => [src, {
      dest: (saved[src] && saved[src].destination) || "",
      project: (saved[src] && saved[src].project_id) || "auto" }])));
    note(`Bundle verified: ${info.chats.length} conversations. Select chats and map their folders.`, "ok");
  };

  const browseBundle = async () => {
    const chosen = await call("pick_file", "bundle").catch(() => null);
    if (chosen) { setPath(chosen); load(chosen); }
  };
  const browseDest = async (source) => {
    const chosen = await call("pick_folder").catch(() => null);
    if (chosen) { setMaps((m) => ({ ...m, [source]: { ...m[source], dest: chosen } })); invalidate(); }
  };
  const setMap = (source, patch) => { setMaps((m) => ({ ...m, [source]: { ...m[source], ...patch } })); invalidate(); };
  const toggle = (id) => { setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); invalidate(); };

  const args = () => {
    const destinations = {}, projects = {};
    sources.forEach((s) => { destinations[s] = (maps[s] && maps[s].dest) || ""; projects[s] = maps[s] && maps[s].project !== "auto" ? maps[s].project : null; });
    return [bundle.path, [...picked], destinations, projects, bundle.hash];
  };
  const missingDest = sources.some((s) => !(maps[s] && maps[s].dest.trim()));
  const canReview = !busy && !stale && picked.size > 0 && !missingDest;

  const review = async () => {
    const out = await run("Comparing selected chats with local histories…", () => call("review_import", ...args()));
    if (out) { setPlans(out); note("Import preview is ready. Branches and older copies are preserved."); }
  };

  const doImport = async () => {
    setConfirm(false);
    const out = await run("Importing selected conversations…", () => call("run_import", ...args()));
    if (!out) return;
    setResult(out);
    setPlans(null);
    const s = await call("get_settings").catch(() => null);
    if (s) setSettings(s);
    reload();
  };

  const title = (id) => (chats.find((c) => c.id === id) || {}).title;

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>Import a bundle</h1>
          <p className="sub">Choose a bundle from the exchange folder, map its folders to this device, review, then import.</p>
        </div>
      </header>

      <div className="toolbar">
        <select className="input" value="" disabled={busy} onChange={(e) => { if (e.target.value) { setPath(e.target.value); load(e.target.value); } }}>
          <option value="">Bundles in exchange folder…</option>
          {data.bundles.map((b) => <option key={b.path} value={b.path}>{b.name}</option>)}
        </select>
        <input className="input grow" placeholder="…or enter a bundle path" value={path} onChange={(e) => setPath(e.target.value)} />
        <button className="btn" disabled={busy} onClick={browseBundle}>Browse</button>
        <button className="btn primary" disabled={busy || !path.trim()} onClick={() => load()}>Load bundle</button>
      </div>

      {!bundle ? <div className="panel"><Empty>Load a bundle to see the conversations inside it.</Empty></div> : (
        <>
          <div className="meta">
            From <b>{bundle.source_device || "unknown device"}</b> · Codex {bundle.codex_version} · {bundle.chats.length} conversation{bundle.chats.length === 1 ? "" : "s"}
            {stale && <span className="warn"> — path changed, load it again</span>}
          </div>
          <div className="split">
            <div className="panel list">
              <div className="list-head">
                <span>Chats in bundle</span>
                <span className="links">
                  <button className="link" onClick={() => { setPicked(new Set(chats.map((c) => c.id))); invalidate(); }}>Select all</button>
                  <button className="link" onClick={() => { setPicked(new Set()); invalidate(); }}>Clear</button>
                </span>
              </div>
              {chats.map((c) => (
                <label key={c.id} className="row">
                  <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} />
                  <div className="row-main">
                    <div className="row-title">{c.title}</div>
                    <div className="row-sub">{c.turns} completed turns · {c.cwd}</div>
                  </div>
                </label>
              ))}
            </div>

            <aside className="panel detail">
              <h4>Destination folders</h4>
              {sources.length === 0 && <p className="muted">Select chats to choose where they should live on this device.</p>}
              {sources.map((s) => (
                <div key={s} className="mapping">
                  <div className="kv col"><span>From</span><code>{s}</code></div>
                  <div className="inline">
                    <input className="input grow" placeholder="Existing destination folder" value={maps[s] ? maps[s].dest : ""}
                      onChange={(e) => setMap(s, { dest: e.target.value })} />
                    <button className="btn" disabled={busy} onClick={() => browseDest(s)}>Browse</button>
                  </div>
                  <select className="input" value={maps[s] ? maps[s].project : "auto"} onChange={(e) => setMap(s, { project: e.target.value })}>
                    <option value="auto">Bundle project / unassigned</option>
                    {data.projects.map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}
                  </select>
                </div>
              ))}

              {plans && (
                <div className="review">
                  <h4>Review</h4>
                  {plans.map((p) => (
                    <div key={p.node} className="plan">
                      <Badge action={p.action} />
                      <div><div className="row-title">{p.title || title(p.node)}</div><div className="row-sub">{p.destination}</div></div>
                    </div>
                  ))}
                </div>
              )}
            </aside>
          </div>

          <div className="actionbar">
            <span className="grow counter">{picked.size} selected{missingDest ? " · choose a destination for every folder" : ""}</span>
            <button className="btn" disabled={!canReview} onClick={review}>Review import</button>
            <button className="btn primary" disabled={busy || !plans} onClick={() => setConfirm(true)}>Import selected</button>
          </div>
        </>
      )}

      {confirm && plans && (
        <Modal title="Confirm import" onClose={() => setConfirm(false)}
          actions={<><button className="btn ghost" onClick={() => setConfirm(false)}>Back</button><button className="btn primary" onClick={doImport}>Import</button></>}>
          {plans.map((p) => (
            <div key={p.node} className="plan"><Badge action={p.action} /><div><div className="row-title">{p.title || title(p.node)}</div><div className="row-sub">{p.destination}</div></div></div>
          ))}
          <p className="muted">Different histories stay separate branches. Existing conversations are retained.</p>
        </Modal>
      )}

      {result && (
        <Modal title="Import complete" onClose={() => setResult(null)}
          actions={<button className="btn primary" onClick={() => setResult(null)}>Close</button>}>
          {result.map((p) => (
            <div key={p.node} className="plan">
              <Badge action={p.action} />
              <div className="grow">
                <div className="row-title">{p.title || title(p.node)}</div>
                {p.thread_id
                  ? <div className="inline"><code className="grow">codex resume {p.thread_id}</code><button className="btn small" onClick={() => copyText("codex resume " + p.thread_id)}>Copy</button></div>
                  : <div className="row-sub">Nothing to create — already available here.</div>}
              </div>
            </div>
          ))}
          <p className="muted">If the Codex desktop app doesn't show the chat yet, reopen it or continue from the terminal with the command above.</p>
        </Modal>
      )}
    </section>
  );
}
