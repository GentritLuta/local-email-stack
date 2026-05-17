import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { Save } from "lucide-react";
import { api, NotConnectedError } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Personas() {
  const [content, setContent] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  useEffect(() => { api.personasGet().then(setContent).catch(() => setContent("")); }, []);
  async function save() {
    try {
      await api.personasSave(content ?? "");
      await api.stackRestartService("persona-engine").catch(() => {});
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e) {
      if (e instanceof NotConnectedError) alert("File save requires the native Tauri build.");
    }
  }
  if (content === null) return (<><h1 className="page-title">Personas</h1><EmptyState variant="loading" /></>);
  return (
    <>
      <h1 className="page-title">Personas</h1>
      <p className="page-sub">10 sender personas, one per subdomain. Save reloads the persona-engine.</p>
      {content === "" ? (
        <EmptyState variant="not-connected"
                    message="personas.yaml is in the stack repo at docker/persona-engine/."
                    hint="Set the Stack repo path in Settings → General. Editing requires the native Tauri build." />
      ) : (
        <>
          <div className="toolbar">
            <span style={{ marginLeft: "auto", color: savedAt ? "var(--accent-lime)" : "#64748b" }}>
              {savedAt ? `Saved ${savedAt}` : "Unsaved"}
            </span>
            <button className="primary" onClick={save}><Save size={14} /> Save + restart</button>
          </div>
          <Editor height="calc(100vh - 240px)" theme="vs-dark" language="yaml" value={content}
                  onChange={v => { setContent(v ?? ""); setSavedAt(null); }}
                  options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: "on" }} />
        </>
      )}
    </>
  );
}
