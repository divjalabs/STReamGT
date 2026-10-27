import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth.jsx";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await login(email, password);
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="container narrow">
      <h1>Log in</h1>
      {loc.state?.reset && <p className="muted">✓ Password updated — log in with your new password.</p>}
      <form onSubmit={submit} className="card">
        {err && <p className="error">{err}</p>}
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <button type="submit">Log in</button>
      </form>
      <p className="muted"><Link to="/forgot-password">Forgot password?</Link> · No account? <Link to="/register">Register</Link></p>
    </div>
  );
}
