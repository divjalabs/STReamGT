import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="container narrow">
      <h1>Reset password</h1>
      {sent ? (
        <div className="card">
          <p>If an account exists for <b>{email}</b>, a reset link has been sent. Check your inbox.</p>
        </div>
      ) : (
        <form onSubmit={submit} className="card">
          {err && <p className="error">{err}</p>}
          <p className="muted">Enter your email and we'll send you a link to reset your password.</p>
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <button type="submit">Send reset link</button>
        </form>
      )}
      <p className="muted"><Link to="/login">Back to log in</Link></p>
    </div>
  );
}
