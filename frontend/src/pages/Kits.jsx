import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, uploadFile } from "../api/client.js";

const KIT_STATUS_CLASS = { analysed: "ok", reanalyse: "warn", received: "", sent: "muted" };
const JOB_STATUS_CLASS = { succeeded: "ok", failed: "error", queued: "muted" };
const TERMINAL = ["succeeded", "failed"];

// Per-kit FASTQ reads: shows the saved pair (if any) and lets an admin/user upload or replace it.
function ReadsUploader({ kit, onChange }) {
  const [open, setOpen] = useState(false);
  const [f1, setF1] = useState(null);
  const [f2, setF2] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const reads = kit.reads;

  const upload = async () => {
    if (!f1 || !f2) return setErr("Choose both R1 and R2 files.");
    setBusy(true); setErr(null);
    try {
      const k1 = await uploadFile(f1, "fastq", () => {}, kit.id);
      const k2 = await uploadFile(f2, "fastq", () => {}, kit.id);
      await api.setKitReads(kit.id, {
        fastq1_key: k1, fastq2_key: k2, fastq1_name: f1.name, fastq2_name: f2.name,
        size1: f1.size, size2: f2.size,
      });
      setOpen(false); setF1(null); setF2(null);
      onChange();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="kit-reads">
      <span className="muted small">
        {reads
          ? `Reads: ${reads.fastq1_name || "R1"} + ${reads.fastq2_name || "R2"} · ${new Date(reads.uploaded_at).toLocaleDateString()}`
          : "No reads on server"}
      </span>{" "}
      <button type="button" className="linkish" onClick={() => setOpen((v) => !v)}>
        {reads ? "replace" : "upload reads"}
      </button>
      {open && (
        <div className="reads-form">
          {err && <p className="error small">{err}</p>}
          <label className="small">R1 <input type="file" accept=".gz,.fastq" onChange={(e) => setF1(e.target.files[0])} /></label>
          <label className="small">R2 <input type="file" accept=".gz,.fastq" onChange={(e) => setF2(e.target.files[0])} /></label>
          <div className="submit-bar">
            <button type="button" disabled={busy} onClick={upload}>{busy ? "Uploading…" : "Save to kit"}</button>{" "}
            <button type="button" className="secondary" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

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
                    {(k.controls || []).some((c) => c.position) && (
                      <button className="secondary" onClick={() =>
                        api.downloadKitTemplate(k.id, `${k.kit_code}_plate_template.xlsx`).catch((e) => setErr(e.message))}>
                        ⭳ Plate template
                      </button>
                    )}
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
                <ReadsUploader kit={k} onChange={load} />
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
