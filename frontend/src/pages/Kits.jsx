import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

const KIT_STATUS_CLASS = { analysed: "ok", reanalyse: "warn", received: "", sent: "muted" };
const JOB_STATUS_CLASS = { succeeded: "ok", failed: "error", queued: "muted" };
const TERMINAL = ["succeeded", "failed"];

// My kits — each kit shows its analyses (jobs) underneath, plus a "Run analysis" shortcut.
export default function Kits() {
  const [kits, setKits] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [err, setErr] = useState(null);
  const [query, setQuery] = useState("");
  const [species, setSpecies] = useState("");

  const load = () => {
    api.listKits().then(setKits).catch((e) => setErr(e.message));
    api.listJobs().then(setJobs).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const markReceived = async (id) => {
    try { await api.updateKit(id, { status: "received" }); load(); }
    catch (e) { setErr(e.message); }
  };

  const jobsFor = (kitId) =>
    jobs.filter((j) => j.kit_id === kitId).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const kitBusy = (kitId) => jobs.some((j) => j.kit_id === kitId && !TERMINAL.includes(j.status));

  const speciesList = [...new Set((kits || []).map((k) => k.species).filter(Boolean))].sort();
  const q = query.trim().toLowerCase();
  const shown = (kits || []).filter(
    (k) =>
      (!species || k.species === species) &&
      (!q || k.kit_code.toLowerCase().includes(q))
  );

  return (
    <div className="container">
      <div className="report-head">
        <h1>My kits</h1>
        <Link to="/submit"><button>New analysis</button></Link>
      </div>
      {err && <p className="error">{err}</p>}
      {kits && kits.length > 0 && (
        <div className="kit-filters">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by kit name…"
          />
          <select value={species} onChange={(e) => setSpecies(e.target.value)}>
            <option value="">All species</option>
            {speciesList.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          {(query || species) && (
            <button type="button" className="secondary" onClick={() => { setQuery(""); setSpecies(""); }}>
              Clear
            </button>
          )}
        </div>
      )}
      {!kits ? <p>Loading…</p> : kits.length === 0 ? (
        <p className="muted">No kits assigned to you yet. An admin registers and assigns kits.</p>
      ) : shown.length === 0 ? (
        <p className="muted">No kits match your filters.</p>
      ) : (
        <div className="kit-list">
          {shown.map((k) => {
            const busy = kitBusy(k.id);
            const canRun = k.status !== "analysed" && !busy;
            const kjobs = jobsFor(k.id);
            return (
              <div className="kit-block" key={k.id}>
                <div className="kit-head">
                  <div>
                    <strong>{k.kit_code}</strong>{" "}
                    <span className={`badge ${KIT_STATUS_CLASS[k.status] || ""}`}>{k.status}</span>
                    <div className="muted small">{k.species || "—"} · {k.tag_columns.map((t) => t.name).join(", ")}</div>
                    {k.updated_at && (
                      <div className="muted small">Status updated {new Date(k.updated_at).toLocaleDateString()}</div>
                    )}
                  </div>
                  <div className="kit-actions">
                    {canRun && <Link to={`/submit?kit=${k.id}`}><button>▶ Run analysis</button></Link>}
                    {k.status === "sent" && (
                      <button className="secondary" onClick={() => markReceived(k.id)}>Mark received</button>
                    )}
                    {k.status === "analysed" && (
                      <span className="muted small">analysed — contact admin to reanalyse</span>
                    )}
                    {busy && <span className="muted small">a job is running</span>}
                  </div>
                </div>
                {kjobs.length === 0 ? (
                  <p className="muted small kit-nojobs">No analyses yet.</p>
                ) : (
                  <table className="table kit-jobs">
                    <thead><tr><th>Analysis</th><th>Status</th><th>Submitted</th><th></th></tr></thead>
                    <tbody>
                      {kjobs.map((j) => (
                        <tr key={j.public_id}>
                          <td className="mono">{j.public_id.slice(0, 8)}</td>
                          <td><span className={`badge ${JOB_STATUS_CLASS[j.status] || ""}`}>{j.status}</span></td>
                          <td className="muted">{new Date(j.created_at).toLocaleString()}</td>
                          <td>
                            <Link to={`/jobs/${j.public_id}`}>
                              {j.status === "succeeded" ? "see results →" : "see details →"}
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
