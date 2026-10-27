import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import AssigneePicker from "../../components/AssigneePicker.jsx";

const STATUSES = ["sent", "received", "analysed", "reanalyse"];
const STATUS_CLASS = { analysed: "ok", reanalyse: "warn", received: "", sent: "muted" };

export default function AdminKits() {
  const [kits, setKits] = useState([]);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);

  // claim codes shown once after regenerate
  const [newCodes, setNewCodes] = useState([]);

  // row editing
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState({ status: "sent", assigned_user_ids: [] });

  const load = () => api.listKits().then(setKits).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listUsers().then(setUsers).catch((e) => setErr(e.message));
  }, []);

  const emailFor = (id) => users.find((u) => u.id === id)?.email || `#${id}`;

  const regenCode = async (id) => {
    try { const k = await api.regenerateClaimCode(id); setNewCodes([{ kit_code: k.kit_code, claim_code: k.claim_code }]); }
    catch (e) { setErr(e.message); }
  };

  const startEdit = (k) => {
    setEditId(k.id);
    // Don't send `description` at all — this form doesn't edit it, and sending "" wiped it.
    setEdit({ status: k.status, assigned_user_ids: [...k.assigned_user_ids] });
  };
  const saveEdit = async (id) => {
    try { await api.updateKit(id, edit); setEditId(null); load(); } catch (e) { setErr(e.message); }
  };
  const remove = async (k) => {
    setErr(null);
    if (k.status === "analysed") {
      alert(`Kit ${k.kit_code} has been analysed and cannot be deleted — its samples and analysis results depend on it.`);
      return;
    }
    if (!confirm(`Delete kit ${k.kit_code}?`)) return;
    try { await api.deleteKit(k.id); load(); } catch (e) { setErr(e.message); }
  };

  return (
    <div className="container">
      <div className="row">
        <h1>Kits (admin)</h1>
        <span className="spacer" />
        <Link to="/admin/kits/new"><button>＋ Register kit(s)</button></Link>
      </div>
      {err && <p className="error">{err}</p>}

      {newCodes.length > 0 && (
        <section className="card claim-codes-card">
          <div className="row">
            <b>Claim code{newCodes.length > 1 ? "s" : ""} — copy now, shown only once</b>
            <span className="spacer" />
            <button type="button" className="link" onClick={() => setNewCodes([])}>dismiss</button>
          </div>
          <p className="muted small">Ship each code with its kit. The buyer redeems it to unlock the kit — no admin step.</p>
          <table className="table">
            <tbody>
              {newCodes.map((c) => (
                <tr key={c.kit_code}>
                  <td>{c.kit_code}</td>
                  <td className="mono"><b>{c.claim_code}</b></td>
                  <td><button type="button" className="linkish" onClick={() => navigator.clipboard?.writeText(c.claim_code)}>copy</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <h2>All kits <span className="muted">({kits.length})</span></h2>
      <table className="table">
        <thead>
          <tr><th>Kit</th><th>Species</th><th>Tags</th><th>Assigned to</th><th>Claimed by</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {kits.map((k) => editId === k.id ? (
            <tr key={k.id}>
              <td>{k.kit_code}</td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td><AssigneePicker users={users} value={edit.assigned_user_ids}
                    onChange={(v) => setEdit({ ...edit, assigned_user_ids: v })} /></td>
              <td className="muted">{k.claimed_by_email || "—"}</td>
              <td>
                <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </td>
              <td>
                <button className="secondary" onClick={() => saveEdit(k.id)}>Save</button>{" "}
                <button className="link" onClick={() => setEditId(null)}>cancel</button>
              </td>
            </tr>
          ) : (
            <tr key={k.id}>
              <td>
                {k.kit_code}
                {k.description && <div className="muted small">{k.description}</div>}
              </td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td className="muted">{k.assigned_user_ids.map(emailFor).join(", ") || "—"}</td>
              <td className="muted">{k.claimed_by_email || "unclaimed"}</td>
              <td><span className={`badge ${STATUS_CLASS[k.status] || ""}`}>{k.status}</span></td>
              <td>
                <button className="secondary" onClick={() => startEdit(k)}>edit</button>{" "}
                <button className="linkish" onClick={() => regenCode(k.id)}>code</button>{" "}
                <button className="link" onClick={() => remove(k)}>delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
