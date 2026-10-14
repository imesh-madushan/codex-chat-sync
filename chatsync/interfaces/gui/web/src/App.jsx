import { useCallback, useEffect, useRef, useState } from "react";
import { call, isMock } from "./api";
import ChatsTab from "./ChatsTab";
import ImportTab from "./ImportTab";
import HistoryTab from "./HistoryTab";
import SettingsTab from "./SettingsTab";

const TABS = [
  { id: "chats", label: "Chats", icon: "💬" },
  { id: "import", label: "Import", icon: "⬇" },
  { id: "history", label: "History", icon: "↺" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

export default function App() {
  const [tab, setTab] = useState("chats");
  const [settings, setSettings] = useState(null);
  const [data, setData] = useState({ threads: [], projects: [], bundles: [], history: [] });
  const [archived, setArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [log, setLog] = useState([]);
  const [toast, setToast] = useState(null);
  const [mock, setMock] = useState(false);
  const busyRef = useRef(false);

  const note = useCallback((message, kind = "info") => {
    setLog((l) => [...l.slice(-199), { t: new Date().toLocaleTimeString(), message, kind }]);
  }, []);

  // Python pushes real phase messages here (no fake percentages).
  useEffect(() => {
    window.__chatsyncProgress = (message) => { setStatus(message); note(message); };
    return () => { delete window.__chatsyncProgress; };
  }, [note]);

  useEffect(() => { isMock().then(setMock); }, []);

  // One operation at a time, mirroring the Textual interface.
  const run = useCallback(async (label, task) => {
    if (busyRef.current) { setToast({ kind: "warn", text: "Wait for the current operation to finish." }); return undefined; }
    busyRef.current = true;
    setBusy(true);
    setStatus(label);
    note(label);
    try {
      const result = await task();
      setStatus("Ready");
      return result;
    } catch (error) {
      setStatus("Operation stopped: " + error.message);
      note(error.message, "error");
      setToast({ kind: "error", text: error.message });
      return undefined;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [note]);

  const reload = useCallback(async (includeArchived = archived) => {
    const result = await run("Loading local chats and projects…", () => call("load_snapshot", includeArchived));
    if (result) { setData(result); note(`Loaded ${result.threads.length} chats and ${result.projects.length} projects.`, "ok"); }
  }, [archived, run, note]);

  useEffect(() => {
    (async () => {
      const s = await call("get_settings").catch(() => null);
      setSettings(s);
      if (s && s.configured) reload(false); else setTab("settings");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const id = setTimeout(() => setToast(null), 7000);
    return () => clearTimeout(id);
  }, [toast]);

  const shared = { busy, run, note, settings, setSettings, data, setData, reload, setToast };

  return (
    <div className="shell">
      <nav className="rail">
        <div className="brand"><span className="logo">⇄</span><span>Chat Sync</span></div>
        {TABS.map((t) => (
          <button key={t.id} className={"rail-btn" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
            <span className="rail-icon" aria-hidden>{t.icon}</span>{t.label}
          </button>
        ))}
        <div className="rail-foot">
          <div className="device">{settings && settings.values ? settings.values.device_name : ""}</div>
          {mock && <div className="mock">browser mock data</div>}
        </div>
      </nav>

      <main className="main">
        {tab === "chats" && <ChatsTab {...shared} archived={archived}
          setArchived={(v) => { setArchived(v); reload(v); }} goImport={() => setTab("import")} />}
        {tab === "import" && <ImportTab {...shared} />}
        {tab === "history" && <HistoryTab {...shared} />}
        {tab === "settings" && <SettingsTab {...shared} afterSave={() => { reload(false); setTab("chats"); }} />}
      </main>

      <footer className="activity">
        <div className="status-row">
          {busy && <span className="spinner" aria-label="working" />}
          <span className={"status" + (status.startsWith("Operation stopped") ? " status-error" : "")}>{status}</span>
        </div>
        <div className="log">
          {log.slice(-6).map((l, i) => <div key={i} className={"log-line log-" + l.kind}><span>{l.t}</span> {l.message}</div>)}
        </div>
      </footer>

      {toast && <div className={"toast toast-" + toast.kind} onClick={() => setToast(null)}>{toast.text}</div>}
    </div>
  );
}
