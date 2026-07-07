import { Routes, Route, Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Jobs from "./pages/Jobs.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Submit from "./pages/Submit.jsx";
import Kits from "./pages/Kits.jsx";
import AdminKits from "./pages/admin/AdminKits.jsx";
import AdminPanels from "./pages/admin/AdminPanels.jsx";
import AdminUsers from "./pages/admin/AdminUsers.jsx";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="container">Loading…</div>;
  return user ? children : <Navigate to="/login" replace />;
}

function AdminProtected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="container">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return user.role === "admin" ? children : <Navigate to="/" replace />;
}

function Nav() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  if (!user) return null;
  const isAdmin = user.role === "admin";
  return (
    <header className="nav">
      <Link to="/" className="brand">STReamGT</Link>
      <nav>
        <Link to="/">My jobs</Link>
        <Link to="/kits">My kits</Link>
        <Link to="/submit">New analysis</Link>
        {isAdmin && <span className="nav-sep">·</span>}
        {isAdmin && <Link to="/admin/kits">Kits</Link>}
        {isAdmin && <Link to="/admin/panels">Panels</Link>}
        {isAdmin && <Link to="/admin/users">Users</Link>}
      </nav>
      <span className="spacer" />
      <span className="muted">{user.email}{isAdmin ? " (admin)" : ""}</span>
      <button onClick={() => { logout(); nav("/login"); }}>Log out</button>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Nav />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<Protected><Jobs /></Protected>} />
        <Route path="/kits" element={<Protected><Kits /></Protected>} />
        <Route path="/submit" element={<Protected><Submit /></Protected>} />
        <Route path="/jobs/:publicId" element={<Protected><JobDetail /></Protected>} />
        <Route path="/admin/kits" element={<AdminProtected><AdminKits /></AdminProtected>} />
        <Route path="/admin/panels" element={<AdminProtected><AdminPanels /></AdminProtected>} />
        <Route path="/admin/users" element={<AdminProtected><AdminUsers /></AdminProtected>} />
      </Routes>
    </>
  );
}
