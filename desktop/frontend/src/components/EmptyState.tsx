import { ServerOff, AlertCircle, Loader2 } from "lucide-react";

type Variant = "not-connected" | "no-data" | "error" | "loading";

export function EmptyState(props: {
  variant: Variant;
  title?: string;
  message?: string;
  hint?: string;
  action?: { label: string; onClick: () => void };
}) {
  const v = props.variant;
  const icon = v === "loading"
    ? <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
    : v === "error"
    ? <AlertCircle size={20} color="var(--accent-red)" />
    : <ServerOff size={20} color="var(--fg-2)" />;
  const defaultTitle = {
    "not-connected": "Stack not connected",
    "no-data": "No data yet",
    "error": "Couldn't load",
    "loading": "Loading…",
  }[v];
  return (
    <div className="card" style={{
      display: "grid", placeItems: "center",
      minHeight: 220, textAlign: "center", color: "var(--fg-1)",
    }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <div>{icon}</div>
        <div style={{ fontWeight: 600, color: "var(--fg-0)" }}>{props.title ?? defaultTitle}</div>
        {props.message && <div style={{ maxWidth: 480 }}>{props.message}</div>}
        {props.hint && <div style={{ fontSize: 12, color: "var(--fg-2)", maxWidth: 480 }}>{props.hint}</div>}
        {props.action && (
          <button className="primary" onClick={props.action.onClick} style={{ marginTop: 4 }}>
            {props.action.label}
          </button>
        )}
      </div>
    </div>
  );
}
