import { Routes, Route, Navigate, Link } from "react-router-dom";
import Onboard from "./routes/Onboard";
import Status from "./routes/Status";
import Dashboard from "./routes/Dashboard";

export default function App() {
  return (
    <div className="wrap">
      <Link to="/" className="brand" style={{ textDecoration: "none", color: "inherit" }}>
        <span className="dot" />
        <h1>AUREON · Client Portal</h1>
      </Link>
      <Routes>
        <Route path="/" element={<Onboard />} />
        <Route path="/status/:id" element={<Status />} />
        <Route path="/dashboard/:slug" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
