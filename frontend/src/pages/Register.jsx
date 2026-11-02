import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";

// The browser's own type="email" accepts things the server rejects (a@b has no dot), so the form
// would submit, come back 422, and look like a server fault. This is the same shape of check
// ResetPassword.jsx does for passwords; the server stays the authority on what is a real address.
const LOOKS_LIKE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisation, setOrg] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    const address = email.trim();
    if (!LOOKS_LIKE_EMAIL.test(address))
      return setErr("That doesn't look like an email address.");
    if (password.length < 8)
      return setErr("Your password needs at least 8 characters.");
    setBusy(true);
    try {
      await register(address, password, organisation.trim() || null);
      nav("/");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
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
        <button type="submit" disabled={busy}>{busy ? "Creating…" : "Register"}</button>
      </form>
      <p className="muted">
        Have a kit? Add it from <b>My kits</b> once you're in, using the claim code on its sticker.
      </p>
      <p className="muted">Have an account? <Link to="/login">Log in</Link></p>
    </div>
  );
}
