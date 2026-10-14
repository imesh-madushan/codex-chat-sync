import { useState } from "react";
import { call } from "./api";
import { Empty, Modal } from "./ui";

export default function HistoryTab({ busy, run, data, setData }) {
  const [selected, setSelected] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const rows = data.history;

  const refresh = async () => {
    const out = await run("Loading operation journals…", () => call("load_history"));
    if (out) { setData((d) => ({ ...d, history: out })); setSelected(null); }
  };

  const rollback = async () => {
    setConfirm(false);
    const out = await run("Rolling back imported copies…", () => call("rollback", selected));
    if (out) { setData((d) => ({ ...d, history: out })); setSelected(null); }
  };

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>Import history</h1>
          <p className="sub">Rollback archives the imported copies. Their messages stay recoverable and your original chats are untouched.</p>
        </div>
        <button className="btn ghost" disabled={busy} onClick={refresh}>Refresh</button>
      </header>

      <div className="panel list">
        {rows.length === 0 ? <Empty>No imports yet.</Empty> : (
          <table className="table">
            <thead><tr><th>Created</th><th>Status</th><th>Conversations</th><th>Operation</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.operation} className={selected === r.operation ? "selected" : ""} onClick={() => setSelected(r.operation)}>
                  <td>{(r.created_at || "").slice(0, 19).replace("T", " ")}</td>
                  <td><span className={"pill pill-" + r.status}>{r.status.replace("_", " ")}</span></td>
                  <td>{r.title}</td>
                  <td><code>{r.operation.slice(0, 12)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="actionbar">
        <span className="grow counter">{selected ? "Operation " + selected.slice(0, 12) + " selected" : "Select an operation"}</span>
        <button className="btn danger" disabled={busy || !selected} onClick={() => setConfirm(true)}>Roll back selected</button>
      </div>

      {confirm && (
        <Modal title="Roll back import" onClose={() => setConfirm(false)}
          actions={<><button className="btn ghost" onClick={() => setConfirm(false)}>Back</button><button className="btn danger" onClick={rollback}>Archive copies</button></>}>
          <p>Archive the imported copies for this operation?</p>
          <p className="muted">Their messages remain recoverable in Codex's archive. Original conversations and native forks remain available.</p>
          <code className="block">{selected}</code>
        </Modal>
      )}
    </section>
  );
}
