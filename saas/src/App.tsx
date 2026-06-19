import { Routes, Route, Navigate, Link } from "react-router-dom";
import Onboard from "./routes/Onboard";
import Learn from "./routes/Learn";
import Sign from "./routes/Sign";
import Access from "./routes/Access";
import Continuation from "./routes/Continuation";
import Billing from "./routes/Billing";
import Status from "./routes/Status";
import Dashboard from "./routes/Dashboard";
import Login from "./routes/Login";
import ResetPassword from "./routes/ResetPassword";
import AuthCallback from "./routes/AuthCallback";
import Admin from "./routes/Admin";
import Security from "./routes/Security";
import { ProtectedRoute, AdminRoute } from "./components/Guards";
import { useAuth } from "./lib/auth";
import Logo from "./components/Logo";

function Header() {
  const { session, isAdmin, signOut } = useAuth();
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
      <Link to={isAdmin ? "/admin" : "/"} style={{ textDecoration: "none" }}>
        <Logo size={38} />
      </Link>
      {session && (
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          {isAdmin && (
            <Link to="/admin" className="btn secondary" style={{ marginTop: 0, padding: "7px 14px", fontSize: 13 }}>
              Admin
            </Link>
          )}
          <Link to="/security" className="hint" style={{ marginTop: 0 }}>Security</Link>
          <span className="hint" style={{ marginTop: 0 }}>{session.user.email}</span>
          <button className="btn ghost" style={{ marginTop: 0, padding: "7px 14px", fontSize: 13 }} onClick={() => signOut()}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <div className="wrap">
      <Header />
      <Routes>
        <Route path="/" element={<Onboard />} />
        <Route path="/learn/:service" element={<Learn />} />
        <Route path="/login" element={<Login />} />
        <Route path="/reset" element={<ResetPassword />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/sign/:id" element={<ProtectedRoute><Sign /></ProtectedRoute>} />
        <Route path="/access/:id" element={<ProtectedRoute><Access /></ProtectedRoute>} />
        <Route path="/continuation/:id" element={<ProtectedRoute><Continuation /></ProtectedRoute>} />
        <Route path="/billing/:id" element={<ProtectedRoute><Billing /></ProtectedRoute>} />
        <Route path="/status/:id" element={<ProtectedRoute><Status /></ProtectedRoute>} />
        <Route path="/dashboard/:slug" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
        <Route path="/admin" element={<AdminRoute><Admin /></AdminRoute>} />
        <Route path="/security" element={<ProtectedRoute><Security /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
