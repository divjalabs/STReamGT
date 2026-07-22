import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import TargetPicker from "../components/TargetPicker.jsx";

const STEPS = ["queued", "staging", "running", "uploading", "succeeded"];
const REPORT_KINDS = ["html_report", "consensus_report"];
const EMPTY_TARGET = { project_id: null, default_population_id: null, default_study_id: null };

export default function JobDetail() {
  const { publicId } = useParams();
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);   // bump to restart live polling (after a rerun)
  const [showReanalysis, setShowReanalysis] = useState(false);
  const [reason, setReason] = useState("");
  const [reanalysisSent, setReanalysisSent] = useState(false);
  const [reErr, setReErr] = useState(null);
  const [showErrReport, setShowErrReport] = useState(false);
  const [errNote, setErrNote] = useState("");
  const [errReportSent, setErrReportSent] = useState(false);
  const [errReportErr, setErrReportErr] = useState(null);
  const [assignTarget, setAssignTarget] = useState(EMPTY_TARGET);
  const [assignMsg, setAssignMsg] = useState(null);
  const [assignErr, setAssignErr] = useState(null);

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

  const rerun = async () => {
    setBusy(true); setErr(null);
    try {
      const j = await api.rerunJob(publicId);
      setJob(j); setResults([]); setTick((t) => t + 1);   // restart polling from queued
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const assign = async () => {
    setBusy(true); setAssignErr(null); setAssignMsg(null);
    try {
      const r = await api.ingestJob(publicId, assignTarget);
      setAssignMsg({ n: r.samples, pop: assignTarget.default_population_id });
    } catch (e) {
      setAssignErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const reportError = async () => {
    setBusy(true); setErrReportErr(null);
    try {
      await api.reportJobError(publicId, errNote.trim() || null);
      setErrReportSent(true); setShowErrReport(false);
    } catch (e) {
      setErrReportErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const submitReanalysis = async () => {
    setBusy(true);
    setReErr(null);
    try {
      await api.requestReanalysis(publicId, reason);
      setReanalysisSent(true);
      setShowReanalysis(false);
    } catch (e) {
      setReErr(e.message);
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
  }, [publicId, tick]);

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
          <div className="submit-bar">
            <button disabled={busy} onClick={rerun}>↻ Rerun analysis</button>{" "}
            {errReportSent ? (
              <span className="muted">✓ Admin notified.</span>
            ) : !showErrReport ? (
              <button type="button" className="secondary" disabled={busy}
                      onClick={() => setShowErrReport(true)}>Notify admin</button>
            ) : null}
          </div>
          {showErrReport && !errReportSent && (
            <div style={{ marginTop: ".5rem" }}>
              <p className="muted small">The error above will be sent to the admins. Add any context (optional).</p>
              {errReportErr && <p className="error">{errReportErr}</p>}
              <textarea rows={3} value={errNote} onChange={(e) => setErrNote(e.target.value)}
                        placeholder="Optional note for the admin…" />
              <div className="submit-bar">
                <button type="button" disabled={busy} onClick={reportError}>
                  {busy ? "Sending…" : "Send to admin"}
                </button>{" "}
                <button type="button" className="secondary" disabled={busy}
                        onClick={() => setShowErrReport(false)}>Cancel</button>
              </div>
            </div>
          )}
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
                <span>{r.filename}</span>
                {REPORT_KINDS.includes(r.kind) && r.view_url && (
                  <a href={r.view_url} target="_blank" rel="noreferrer">Open ↗</a>
                )}
                <a href={r.url}>Download</a>
              </li>
            ))}
          </ul>

          <div className="card">
            <h2>Assign to project <span className="muted small">(for consensus &amp; matching)</span></h2>
            <p className="muted small">Assign this run's samples to a project/population/study — no
              re-run. Pick a <b>population</b> to make the samples available for consensus and matching.</p>
            {assignErr && <p className="error">{assignErr}</p>}
            {assignMsg ? (
              <p className="ok">✓ Assigned {assignMsg.n} sample(s).{" "}
                {assignMsg.pop && <Link to={`/populations/${assignMsg.pop}/samples`}>View samples →</Link>}
              </p>
            ) : (
              <>
                <TargetPicker value={assignTarget} onChange={setAssignTarget} disabled={busy} />
                <div className="submit-bar">
                  <button type="button" disabled={busy || !assignTarget.project_id} onClick={assign}>
                    {busy ? "Assigning…" : "Assign to project"}
                  </button>
                </div>
              </>
            )}
          </div>

          <div className="card">
            <h2>Need another run?</h2>
            {reErr && <p className="error">{reErr}</p>}
            {reanalysisSent ? (
              <p className="muted">✓ Reanalysis requested — an admin will review it.</p>
            ) : !showReanalysis ? (
              <button type="button" className="secondary" onClick={() => setShowReanalysis(true)}>
                Request reanalysis
              </button>
            ) : (
              <>
                <p className="muted">
                  This kit is locked as analysed. Explain why it should be re-run — an admin will
                  be notified.
                </p>
                <textarea
                  rows={4}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason for reanalysis…"
                />
                <div className="submit-bar">
                  <button type="button" disabled={busy || !reason.trim()} onClick={submitReanalysis}>
                    {busy ? "Sending…" : "Send request"}
                  </button>{" "}
                  <button type="button" className="secondary" disabled={busy} onClick={() => setShowReanalysis(false)}>
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
