import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client.js";

const STEPS = ["queued", "staging", "running", "rendering", "uploading", "succeeded"];

export default function JobDetail() {
  const { publicId } = useParams();
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const confirm = async (proceed) => {
    setBusy(true);
    try {
      setJob(await api.confirmJob(publicId, proceed));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let timer;
    const poll = async () => {
      try {
        const j = await api.getJob(publicId);
        setJob(j);
        if (j.status === "succeeded") setResults(await api.getResults(publicId));
        if (j.status !== "succeeded" && j.status !== "failed") {
          timer = setTimeout(poll, 4000); // live-track progress
        }
      } catch (e) {
        setErr(e.message);
      }
    };
    poll();
    return () => clearTimeout(timer);
  }, [publicId]);

  if (err) return <div className="container"><p className="error">{err}</p></div>;
  if (!job) return <div className="container">Loading…</div>;

  const stepIdx = STEPS.indexOf(job.status);

  return (
    <div className="container">
      <h1>Analysis {job.public_id.slice(0, 8)}</h1>
      <p className="muted">Kit #{job.kit_id} · submitted {new Date(job.created_at).toLocaleString()}</p>

      {job.status === "awaiting_confirmation" ? (
        <div className="card error-card">
          <b>⚠️ Low read count — confirmation needed</b>
          <p>
            The FASTQ has <b>{job.observed_read_count?.toLocaleString()}</b> reads, below the
            expected <b>{job.expected_read_number?.toLocaleString()}</b>. Run the pipeline anyway?
          </p>
          <button disabled={busy} onClick={() => confirm(true)}>Run anyway</button>{" "}
          <button className="secondary" disabled={busy} onClick={() => confirm(false)}>Cancel</button>
        </div>
      ) : job.status === "failed" ? (
        <div className="card error-card">
          <b>Failed</b>
          <pre>{job.error_message}</pre>
        </div>
      ) : (
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i < stepIdx ? "done" : i === stepIdx ? "active" : ""}>{s}</li>
          ))}
        </ol>
      )}

      <h2>Sample batches</h2>
      <table className="table">
        <thead><tr><th>Batch</th><th>Species</th><th>Tags</th></tr></thead>
        <tbody>
          {job.batches.map((b) => (
            <tr key={b.id}><td>{b.name}</td><td>{b.species || "—"}</td><td>{b.selected_tags.join(", ")}</td></tr>
          ))}
        </tbody>
      </table>

      {job.status === "succeeded" && (
        <>
          <h2>Results</h2>
          <ul className="results">
            {results.map((r) => (
              <li key={r.filename}>
                <span className="badge">{r.kind}</span>
                <a href={r.url}>{r.filename}</a>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
