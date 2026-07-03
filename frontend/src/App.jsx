import { Routes, Route, Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Jobs from "./pages/Jobs.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Submit from "./pages/Submit.jsx";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="container">Loading…</div>;
  return user ? children : <Navigate to="/login" replace />;
}

function Nav() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  if (!user) return null;
  return (
    <header className="nav">
      <Link to="/" className="brand">STReamGT</Link>
      <nav>
        <Link to="/">My jobs</Link>
        <Link to="/submit">New analysis</Link>
      </nav>
      <span className="spacer" />
      <span className="muted">{user.email}</span>
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
        <Route path="/submit" element={<Protected><Submit /></Protected>} />
        <Route path="/jobs/:publicId" element={<Protected><JobDetail /></Protected>} />
      </Routes>
    </>
  );
}
