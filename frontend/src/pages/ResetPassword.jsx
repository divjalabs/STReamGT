import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client.js";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (password.length < 8) return setErr("Password must be at least 8 characters.");
    if (password !== confirm) return setErr("Passwords do not match.");
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      nav("/login", { replace: true, state: { reset: true } });
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <div className="container narrow">
        <h1>Reset password</h1>
        <p className="error">This reset link is missing its token. Please request a new one.</p>
        <p className="muted"><Link to="/forgot-password">Request a reset link</Link></p>
      </div>
    );
  }

  return (
    <div className="container narrow">
      <h1>Set a new password</h1>
      <form onSubmit={submit} className="card">
        {err && <p className="error">{err}</p>}
        <label>New password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
        <label>Confirm password<input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></label>
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save new password"}</button>
      </form>
      <p className="muted"><Link to="/login">Back to log in</Link></p>
    </div>
  );
}
