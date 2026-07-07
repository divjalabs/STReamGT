import { useEffect, useState } from "react";
import { api } from "../api/client.js";

const STATUS_CLASS = { analysed: "ok", received: "", sent: "muted" };

export default function Kits() {
  const [kits, setKits] = useState(null);
  const [err, setErr] = useState(null);

  const load = () => api.listKits().then(setKits).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const markReceived = async (id) => {
    try {
      await api.updateKit(id, { status: "received" });
      load();
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="container">
      <h1>My kits</h1>
      {err && <p className="error">{err}</p>}
      {!kits ? (
        <p>Loading…</p>
      ) : kits.length === 0 ? (
        <p className="muted">No kits assigned to you yet. An admin registers and assigns kits.</p>
      ) : (
        <table className="table">
          <thead>
            <tr><th>Kit</th><th>Species</th><th>Tags</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {kits.map((k) => (
              <tr key={k.id}>
                <td>{k.kit_code}</td>
                <td>{k.species || "—"}</td>
                <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
                <td><span className={`badge ${STATUS_CLASS[k.status] || ""}`}>{k.status}</span></td>
                <td>
                  {k.status === "sent" && (
                    <button className="secondary" onClick={() => markReceived(k.id)}>Mark received</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
