import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { Plus, Trash2, Save, RefreshCw } from "lucide-react";
import { api, NicheSummary, NotConnectedError } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Niches() {
  const [list, setList] = useState<NicheSummary[] | null>(null);
  const [selected, setSelected] = useState<NicheSummary | null>(null);
  const [content, setContent] = useState<string>("");
  const [savedAt, setSavedAt] = useState<string | null>(null);

  async function refresh() {
    try {
      const items = await api.nichesList();
      setList(items);
      if (items.length && !selected) setSelected(items[0]);
    } catch { setList([]); }
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => { if (selected) api.nicheGet(selected.path).then(setContent).catch(() => setContent("")); }, [selected]);

  async function save() {
    if (!selected) return;
    try {
      await api.nicheSave(selected.path, content);
      await api.nicheReloadService().catch(() => {});
      setSavedAt(new Date().toLocaleTimeString());
      await refresh();
    } catch (e) {
      if (e instanceof NotConnectedError) alert("File save requires the native Tauri build (the dev browser can't write to disk).");
    }
  }

  async function remove() {
    if (!selected) return;
    if (!confirm(`Delete ${selected.slug}?`)) return;
    try { await api.nicheDelete(selected.path); setSelected(null); await refresh(); }
    catch (e) { if (e instanceof NotConnectedError) alert("File delete requires the native Tauri build."); }
  }

  if (list === null) return (<><h1 className="page-title">Niches</h1><EmptyState variant="loading" /></>);
  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Niches</h1>
          <p className="page-sub">YAML niche configs. Save reloads the sourcing service.</p>
        </div>
        <div className="row gap-2">
          <button onClick={refresh}><RefreshCw size={14} /> Refresh</button>
          <button><Plus size={14} /> New niche</button>
        </div>
      </div>
      {list.length === 0 ? (
        <EmptyState variant="not-connected"
                    message="Niches load from the niches/ folder in your stack repo."
                    hint="Set the Stack repo path in Settings → General. The dev browser can't read files; switch to the native Tauri build for editing." />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "260px 1fr", gap: 16 }}>
          <div className="card" style={{ padding: 8, maxHeight: "calc(100vh - 220px)", overflow: "auto" }}>
            {list.map(n => (
              <div key={n.path} onClick={() => setSelected(n)}
                   style={{ padding: "8px 12px", borderRadius: 8, cursor: "pointer",
                            background: selected?.path === n.path ? "rgba(34,211,238,0.08)" : undefined }}>
                <div style={{ fontWeight: 500 }}>{n.name || n.slug}</div>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>{n.slug}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="toolbar">
              <span style={{ color: "#94a3b8" }}>{selected?.path}</span>
              <span style={{ marginLeft: "auto", color: savedAt ? "var(--accent-lime)" : "#64748b" }}>
                {savedAt ? `Saved ${savedAt}` : "Unsaved"}
              </span>
              <button className="primary" disabled={!selected} onClick={save}><Save size={14} /> Save + reload</button>
              <button className="danger" disabled={!selected} onClick={remove}><Trash2 size={14} /> Delete</button>
            </div>
            <Editor height="calc(100vh - 280px)" theme="vs-dark" language="yaml" value={content}
                    onChange={v => { setContent(v ?? ""); setSavedAt(null); }}
                    options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: "on" }} />
          </div>
        </div>
      )}
    </>
  );
}
