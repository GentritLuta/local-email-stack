import { useEffect, useRef, useState } from "react";
import { api, ServiceStatus, NotConnectedError } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

const STREAM_ID = "logs-main";

export function LogsPage() {
  const [services, setServices] = useState<ServiceStatus[] | null>(null);
  const [container, setContainer] = useState<string>("");
  const [lines, setLines] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.stackStatus().then(s => { setServices(s); if (s[0]) setContainer(s[0].name); }).catch(() => setServices([]));
  }, []);

  useEffect(() => {
    if (!container) return;
    setLines([]); setErr(null);
    let unlisten: any = null;
    (async () => {
      try {
        unlisten = await api.onLogLine(STREAM_ID, ln => {
          setLines(prev => { const n = [...prev, ln]; return n.length > 2000 ? n.slice(-2000) : n; });
        });
        await api.streamLogs(container, STREAM_ID);
      } catch (e: any) {
        setErr(e instanceof NotConnectedError ? "Log streaming requires the native Tauri build with `docker logs` access." : String(e));
      }
    })();
    return () => { api.stopLogStream(STREAM_ID).catch(() => {}); unlisten && unlisten(); };
  }, [container]);

  useEffect(() => { if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight; }, [lines]);

  if (services === null) return (<><h1 className="page-title">Logs</h1><EmptyState variant="loading" /></>);
  const filtered = filter ? lines.filter(l => l.toLowerCase().includes(filter.toLowerCase())) : lines;
  return (
    <>
      <h1 className="page-title">Logs</h1>
      <p className="page-sub">Tail any container in real time.</p>
      {services.length === 0 ? (
        <EmptyState variant="not-connected"
                    message="Logs stream via `docker logs --follow` from the native Tauri build."
                    hint="Start the stack (Overview → Start stack) in the native build to see logs here." />
      ) : (
        <>
          <div className="toolbar">
            <select value={container} onChange={e => setContainer(e.target.value)}>
              {services.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
            <input type="text" placeholder="Filter (substring)" value={filter} onChange={e => setFilter(e.target.value)} />
            <button onClick={() => setLines([])}>Clear</button>
          </div>
          {err && <div className="card" style={{ borderColor: "var(--accent-red)" }}>{err}</div>}
          <div className="logs" ref={boxRef}>
            {filtered.length === 0 ? <div style={{ color: "var(--fg-2)" }}>No log lines yet.</div> : filtered.map((l, i) => {
              const isErr = l.startsWith("[stderr]");
              const m = l.match(/^(\S+?T\S+?Z)\s/);
              return <div key={i} className={isErr ? "stderr" : ""}>
                {m ? <><span className="ts">{m[1]}</span> {l.slice(m[0].length)}</> : l}
              </div>;
            })}
          </div>
        </>
      )}
    </>
  );
}
