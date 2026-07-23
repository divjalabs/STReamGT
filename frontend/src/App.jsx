import { Routes, Route, Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";
import Home from "./pages/Home.jsx";
import Account from "./pages/Account.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Submit from "./pages/Submit.jsx";
import Kits from "./pages/Kits.jsx";
import Projects from "./pages/projects/Projects.jsx";
import ProjectDetail from "./pages/projects/ProjectDetail.jsx";
import SampleReport from "./pages/samples/SampleReport.jsx";
import SamplePage from "./pages/samples/SamplePage.jsx";
import SampleReplicates from "./pages/samples/SampleReplicates.jsx";
import SamplePlots from "./pages/samples/SamplePlots.jsx";
import AnimalMatch from "./pages/matching/AnimalMatch.jsx";
import AnimalView from "./pages/matching/AnimalView.jsx";
import AdminKits from "./pages/admin/AdminKits.jsx";
import AdminPanels from "./pages/admin/AdminPanels.jsx";
import AdminUsers from "./pages/admin/AdminUsers.jsx";
import Manual from "./pages/Manual.jsx";

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
        <Link to="/">Home</Link>
        <Link to="/kits">My kits</Link>
        <Link to="/projects">Projects</Link>
        {isAdmin && <span className="nav-sep">·</span>}
        {isAdmin && <Link to="/admin/kits">Kits</Link>}
        {isAdmin && <Link to="/admin/panels">Panels</Link>}
        {isAdmin && <Link to="/admin/users">Users</Link>}
      </nav>
      <span className="spacer" />
      <Link to="/account" className="muted">{user.email}{isAdmin ? " (admin)" : ""}</Link>
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
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/" element={<Protected><Home /></Protected>} />
        <Route path="/account" element={<Protected><Account /></Protected>} />
        <Route path="/jobs" element={<Navigate to="/kits" replace />} />
        <Route path="/manuals/:slug" element={<Manual />} />
        <Route path="/kits" element={<Protected><Kits /></Protected>} />
        <Route path="/projects" element={<Protected><Projects /></Protected>} />
        <Route path="/projects/:id" element={<Protected><ProjectDetail /></Protected>} />
        <Route path="/populations/:populationId/samples" element={<Protected><SampleReport /></Protected>} />
        <Route path="/studies/:studyId/samples" element={<Protected><SampleReport /></Protected>} />
        <Route path="/samples/:id" element={<Protected><SamplePage /></Protected>} />
        <Route path="/samples/:id/replicates" element={<Protected><SampleReplicates /></Protected>} />
        <Route path="/samples/:id/plots" element={<Protected><SamplePlots /></Protected>} />
        <Route path="/populations/:populationId/match" element={<Protected><AnimalMatch /></Protected>} />
        <Route path="/animals/:subgroupId" element={<Protected><AnimalView /></Protected>} />
        <Route path="/submit" element={<Protected><Submit /></Protected>} />
        <Route path="/jobs/:publicId" element={<Protected><JobDetail /></Protected>} />
        <Route path="/admin/kits" element={<AdminProtected><AdminKits /></AdminProtected>} />
        <Route path="/admin/panels" element={<AdminProtected><AdminPanels /></AdminProtected>} />
        <Route path="/admin/users" element={<AdminProtected><AdminUsers /></AdminProtected>} />
      </Routes>
    </>
  );
}
