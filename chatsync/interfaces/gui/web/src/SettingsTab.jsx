import { useEffect, useState } from "react";
import { call } from "./api";
import { Field } from "./ui";

const FIELDS = [
  { key: "device_name", label: "Device label", kind: "text", hint: "Shown on branches, e.g. “home-pc”." },
  { key: "codex_home", label: "Codex data folder", kind: "folder", hint: "Usually ~/.codex" },
  { key: "codex_executable", label: "Codex executable", kind: "file", hint: "On Windows pick the real codex.exe, not the .cmd/.ps1 wrapper." },
  { key: "exchange_dir", label: "Bundle exchange folder", kind: "folder", hint: "A folder your file-sync service (OneDrive, Syncthing…) already shares between devices." },
  { key: "state_dir", label: "Local state folder", kind: "folder", hint: "Keep this OUTSIDE any synced folder; it holds this device's receipts." },
];

export default function SettingsTab({ busy, run, note, settings, setSettings, afterSave }) {
  const [values, setValues] = useState({});
  useEffect(() => { if (settings) setValues(settings.values); }, [settings]);

  const browse = async (field) => {
    const chosen = await (field.kind === "folder" ? call("pick_folder") : call("pick_file", "any")).catch(() => null);
    if (chosen) setValues((v) => ({ ...v, [field.key]: chosen }));
  };

  const save = async () => {
    const out = await run("Checking paths and Codex connection…", () => call("save_settings", values));
    if (out) { setSettings(out); note("Device settings saved and Codex connection verified.", "ok"); afterSave(); }
  };

  if (!settings) return <section className="page"><p className="muted">Loading settings…</p></section>;

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h1>Device settings</h1>
          <p className="sub">Saved per device in <code>{settings.settings_path}</code>. {settings.configured ? "" : "Fill these in once to get started."}</p>
        </div>
      </header>
      <div className="panel form">
        {FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <div className="inline">
              <input className="input grow" value={values[f.key] || ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
              {f.kind !== "text" && <button type="button" className="btn" disabled={busy} onClick={() => browse(f)}>Browse</button>}
            </div>
          </Field>
        ))}
      </div>
      <div className="actionbar">
        <span className="grow counter">Saving verifies that Codex starts and its protocol responds.</span>
        <button className="btn primary" disabled={busy} onClick={save}>Save device settings</button>
      </div>
    </section>
  );
}
