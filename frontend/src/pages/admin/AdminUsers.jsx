import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useAuth } from "../../auth.jsx";

export default function AdminUsers() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);

  const load = () => api.listUsers().then(setUsers).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const patch = async (id, body) => {
    try { await api.updateUser(id, body); load(); } catch (e) { setErr(e.message); }
  };

  return (
    <div className="container">
      <h1>Users (admin)</h1>
      {err && <p className="error">{err}</p>}
      <p className="muted">Promote clients to admin or deactivate accounts. Assign kits on the Kits page.</p>
      <table className="table">
        <thead><tr><th>Email</th><th>Organisation</th><th>Role</th><th>Active</th><th></th></tr></thead>
        <tbody>
          {users.map((u) => {
            const self = u.id === me.id;
            return (
              <tr key={u.id}>
                <td>{u.email}{self ? " (you)" : ""}</td>
                <td className="muted">{u.organisation || "—"}</td>
                <td><span className={`badge ${u.role === "admin" ? "ok" : ""}`}>{u.role}</span></td>
                <td>{u.is_active ? "yes" : <span className="error">no</span>}</td>
                <td>
                  {!self && (
                    <>
                      <button className="secondary" onClick={() => patch(u.id, { role: u.role === "admin" ? "user" : "admin" })}>
                        {u.role === "admin" ? "Demote" : "Make admin"}
                      </button>{" "}
                      <button className="link" onClick={() => patch(u.id, { is_active: !u.is_active })}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
