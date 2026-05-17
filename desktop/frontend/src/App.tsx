import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  Activity, Database, Mail, Inbox, Layers, Users, FlaskConical, Settings,
  Send, FileCog, ShieldCheck, Workflow, Rocket, UserRound, Rocket as RocketI, BarChart3
} from "lucide-react";
import { Dashboard } from "./routes/Dashboard";
import { Pipeline } from "./routes/Pipeline";
import { Sourcing } from "./routes/Sourcing";
import { Sequences } from "./routes/Sequences";
import { Warmup } from "./routes/Warmup";
import { Replies } from "./routes/Replies";
import { Bandit } from "./routes/Bandit";
import { Niches } from "./routes/Niches";
import { Personas } from "./routes/Personas";
import { LogsPage } from "./routes/Logs";
import { SettingsPage } from "./routes/Settings";
import { SetupWizard } from "./routes/Setup";
import { Profiles } from "./routes/Profiles";
import { Campaigns } from "./routes/Campaigns";
import { Analytics } from "./routes/Analytics";
import { api } from "./lib/api";
import { ensurePermission } from "./lib/notify";
import { ProfilePicker } from "./components/ProfilePicker";

export function App() {
  const [firstRun, setFirstRun] = useState<boolean | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.detectFirstRun().then((fr) => {
      setFirstRun(fr);
      if (fr) navigate("/setup", { replace: true });
    });
    // Request notification permission once on startup so reply toasts work.
    ensurePermission();
  }, [navigate]);

  if (firstRun === null) {
    return <div style={{ display: "grid", placeItems: "center", height: "100vh", color: "#94a3b8" }}>Loading…</div>;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/icon.svg" alt="LocalEmailStack" />
          <div>
            <div className="title">LocalEmailStack</div>
            <div className="subtitle">v0.4 · self-hosted</div>
          </div>
        </div>
        <ProfilePicker />
        <nav>
          <Item to="/" icon={<Activity size={16} />} label="Overview" end />
          <Item to="/campaigns" icon={<RocketI size={16} />} label="Campaigns" />
          <Item to="/analytics" icon={<BarChart3 size={16} />} label="Analytics" />
          <Item to="/profiles" icon={<UserRound size={16} />} label="Profiles" />
          <Item to="/sequences" icon={<Send size={16} />} label="Sequences" />
          <Item to="/warmup" icon={<ShieldCheck size={16} />} label="Warmup" />
          <Item to="/replies" icon={<Inbox size={16} />} label="Replies" />
          <Item to="/sourcing" icon={<Layers size={16} />} label="Sourcing" />
          <Item to="/pipeline" icon={<Workflow size={16} />} label="Pipeline" />
          <Item to="/bandit" icon={<FlaskConical size={16} />} label="Bandit" />
          <Item to="/niches" icon={<FileCog size={16} />} label="Niches" />
          <Item to="/personas" icon={<Users size={16} />} label="Personas" />
          <Item to="/logs" icon={<Database size={16} />} label="Logs" />
          <Item to="/settings" icon={<Settings size={16} />} label="Settings" />
        </nav>
        <div className="footer">© Insane AI Automation</div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/sourcing" element={<Sourcing />} />
          <Route path="/sequences" element={<Sequences />} />
          <Route path="/warmup" element={<Warmup />} />
          <Route path="/bandit" element={<Bandit />} />
          <Route path="/replies" element={<Replies />} />
          <Route path="/niches" element={<Niches />} />
          <Route path="/personas" element={<Personas />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/setup" element={<SetupWizard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function Item(props: { to: string; icon: React.ReactNode; label: string; end?: boolean }) {
  return (
    <NavLink to={props.to} end={props.end} className={({ isActive }) => isActive ? "active" : ""}>
      {props.icon}
      <span>{props.label}</span>
    </NavLink>
  );
}
