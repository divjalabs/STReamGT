import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

const STATUS_CLASS = {
  succeeded: "ok",
  failed: "error",
  queued: "muted",
};

export default function Jobs() {
  const [jobs, setJobs] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.listJobs().then(setJobs).catch((e) => setErr(e.message));
  }, []);

  return (
    <div className="container">
      <div className="row">
        <h1>My analyses</h1>
        <span className="spacer" />
        <Link to="/submit"><button>New analysis</button></Link>
      </div>
      {err && <p className="error">{err}</p>}
      {!jobs ? (
        <p>Loading…</p>
      ) : jobs.length === 0 ? (
        <p className="muted">No analyses yet. Start one with “New analysis”.</p>
      ) : (
        <table className="table">
          <thead>
            <tr><th>Job</th><th>Kit</th><th>Status</th><th>Submitted</th></tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.public_id}>
                <td><Link to={`/jobs/${j.public_id}`}>{j.public_id.slice(0, 8)}</Link></td>
                <td>{j.kit_id}</td>
                <td><span className={`badge ${STATUS_CLASS[j.status] || ""}`}>{j.status}</span></td>
                <td className="muted">{new Date(j.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
