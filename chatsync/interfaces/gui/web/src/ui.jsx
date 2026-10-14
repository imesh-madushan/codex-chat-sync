import { useEffect } from "react";

export const ACTION_LABELS = { new: "New", update: "Update", branch: "Branch", same: "Duplicate", stale: "Older", relocate: "Relocate" };
export const ACTION_HELP = {
  new: "First time this chat arrives on this device.",
  update: "Extends your local copy; the earlier copy is kept.",
  branch: "Different history; both versions are kept.",
  same: "Already here; nothing is created.",
  stale: "Your local copy is newer; nothing is replaced.",
  relocate: "Same history, different folder/project; a new copy is made.",
};

export function Badge({ action }) {
  return <span className={"badge badge-" + action} title={ACTION_HELP[action]}>{ACTION_LABELS[action] || action}</span>;
}

export function Modal({ title, children, actions, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <div className="modal-body">{children}</div>
        <div className="modal-actions">{actions}</div>
      </div>
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

export function copyText(text) {
  try { navigator.clipboard.writeText(text); } catch { /* clipboard unavailable */ }
}

export function chatTitle(t) {
  return t.name || (t.preview || "").slice(0, 100) || t.id;
}
