import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisation, setOrg] = useState("");
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await register(email, password, organisation || null);
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="container narrow">
      <h1>Create account</h1>
      <form onSubmit={submit} className="card">
        {err && <p className="error">{err}</p>}
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password (min 8)<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required /></label>
        <label>Organisation<input value={organisation} onChange={(e) => setOrg(e.target.value)} /></label>
        <button type="submit">Register</button>
      </form>
      <p className="muted">Have an account? <Link to="/login">Log in</Link></p>
    </div>
  );
}
