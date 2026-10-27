import { useState } from "react";
import { api } from "../api/client.js";
import { useAuth } from "../auth.jsx";

export default function Account() {
  const { user, updateUser } = useAuth();
  const [org, setOrg] = useState(user?.organisation || "");
  const [profileMsg, setProfileMsg] = useState(null);
  const [profileErr, setProfileErr] = useState(null);
  const [savingProfile, setSavingProfile] = useState(false);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwMsg, setPwMsg] = useState(null);
  const [pwErr, setPwErr] = useState(null);
  const [savingPw, setSavingPw] = useState(false);

  if (!user) return null;
  const isAdmin = user.role === "admin";

  const saveProfile = async (e) => {
    e.preventDefault();
    setProfileMsg(null); setProfileErr(null); setSavingProfile(true);
    try {
      const updated = await api.updateProfile({ organisation: org.trim() || null });
      updateUser(updated);
      setProfileMsg("✓ Profile saved.");
    } catch (e) { setProfileErr(e.message); } finally { setSavingProfile(false); }
  };

  const savePassword = async (e) => {
    e.preventDefault();
    setPwMsg(null); setPwErr(null);
    if (next.length < 8) return setPwErr("New password must be at least 8 characters.");
    if (next !== confirm) return setPwErr("New password and confirmation don't match.");
    setSavingPw(true);
    try {
      await api.changePassword(current, next);
      setCurrent(""); setNext(""); setConfirm("");
      setPwMsg("✓ Password changed.");
    } catch (e) { setPwErr(e.message); } finally { setSavingPw(false); }
  };

  return (
    <div className="container narrow">
      <h1>Account</h1>

      <form className="card" onSubmit={saveProfile}>
        <h2>Profile</h2>
        {profileErr && <p className="error">{profileErr}</p>}
        {profileMsg && <p className="ok">{profileMsg}</p>}
        <label>Email <span className="muted">(sign-in identity — not editable)</span>
          <input value={user.email} readOnly disabled />
        </label>
        <p className="row" style={{ gap: ".5rem", alignItems: "center" }}>
          Role <span className={`badge ${isAdmin ? "ok" : ""}`}>{user.role}</span>
        </p>
        <label>Organisation
          <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder="Your lab / company" />
        </label>
        <button type="submit" disabled={savingProfile}>{savingProfile ? "Saving…" : "Save profile"}</button>
      </form>

      <form className="card" onSubmit={savePassword}>
        <h2>Change password</h2>
        {pwErr && <p className="error">{pwErr}</p>}
        {pwMsg && <p className="ok">{pwMsg}</p>}
        <label>Current password<input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required /></label>
        <label>New password (min 8)<input type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength={8} required /></label>
        <label>Confirm new password<input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></label>
        <button type="submit" disabled={savingPw}>{savingPw ? "Changing…" : "Change password"}</button>
      </form>
    </div>
  );
}
