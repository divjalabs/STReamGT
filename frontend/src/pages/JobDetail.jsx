import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { JOB_STEPS as STEPS, isTerminal, isStoppable } from "../config/jobs.js";
import TargetPicker from "../components/TargetPicker.jsx";
const REPORT_KINDS = ["html_report", "consensus_report"];
const CONSENSUS_KINDS = ["consensus", "consensus_report", "reference_alleles"];
const HIDDEN_KINDS = ["reads_summary"];
const KIND_LABEL = {
  consensus: "consensus genotypes",
  consensus_report: "consensus report",
  reference_alleles: "allele sequences",
};
const EMPTY_TARGET = { project_id: null, default_population_id: null, default_study_id: null };

function ResultRow({ r }) {
  return (
    <li>
      <span className="badge">{KIND_LABEL[r.kind] || r.kind}</span>
      <span>{r.filename}</span>
      {REPORT_KINDS.includes(r.kind) && r.view_url && (
        <a href={r.view_url} target="_blank" rel="noreferrer">Open ↗</a>
      )}
      <a href={r.url}>Download</a>
    </li>
  );
}

export default function JobDetail() {
  const { publicId } = useParams();
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const [err, setErr] = useState(null);
  const [stale, setStale] = useState(false);  // a poll failed; showing the last known state
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopErr, setStopErr] = useState(null);
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
  const [kitStudy, setKitStudy] = useState(null);   // the kit's linked study, for the pre-fill hint

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

  const stop = async () => {
    setBusy(true); setStopErr(null);
    try {
      const j = await api.stopJob(publicId);
      setJob(j); setConfirmStop(false); setTick((t) => t + 1);  // let an in-flight poll be replaced
    } catch (e) {
      setStopErr(e.message);
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
    let cancelled = false;
    let timer;
    let failures = 0;
    const MAX_FAILURES = 10;

    const poll = async () => {
      try {
        const j = await api.getJob(publicId);
        if (cancelled) return;
        failures = 0;
        setStale(false);
        setErr(null);
        setJob(j);
        if (j.status === "succeeded") {
          const r = await api.getResults(publicId);
          if (cancelled) return;
          setResults(r);
        }
        if (!isTerminal(j.status)) {
          timer = setTimeout(poll, 4000); // live-track progress
        }
      } catch (e) {
        if (cancelled) return;
        if (e.status === 404) {        // the job is genuinely gone — stop and say so
          setErr(e.message);
          return;
        }
        // A pipeline run lasts hours; one failed poll must not end the page. Keep the last
        // known state on screen, back off, and carry on.
        failures += 1;
        setStale(true);
        if (failures >= MAX_FAILURES) {
          setErr(`Lost contact with the server: ${e.message}`);
          return;
        }
        timer = setTimeout(poll, Math.min(4000 * 2 ** failures, 60000));
      }
    };
    poll();
    return () => {
      cancelled = true;              // a poll already in flight must not schedule another
      clearTimeout(timer);
    };
  }, [publicId, tick]);

  // If this job's kit is linked to a single study, pre-fill the "Assign to project" target from it.
  useEffect(() => {
    if (!job?.kit_id) return;
    api.listKits()
      .then((kits) => kits.find((k) => k.id === job.kit_id))
      .then((k) => {
        if (k?.studies?.length === 1) {
          const s = k.studies[0];
          setKitStudy(s);
          setAssignTarget((t) => (t.project_id ? t : {
            project_id: s.project_id, default_population_id: s.population_id ?? null, default_study_id: s.id,
          }));
        }
      })
      .catch(() => {});
  }, [job?.kit_id]);

  // Only blank the page when there is nothing to show; a hiccup mid-run keeps the last state.
  if (err && !job) return (
    <div className="container">
      <p className="error">{err}</p>
      <button onClick={() => { setErr(null); setTick((t) => t + 1); }}>Try again</button>
    </div>
  );
  if (!job) return <div className="container">Loading…</div>;

  const stepIdx = STEPS.indexOf(job.status);

  return (
    <div className="container">
      <h1>Analysis {job.public_id.slice(0, 8)}</h1>
      <p className="muted">Kit #{job.kit_id} · submitted {new Date(job.created_at).toLocaleString()}</p>

      {stale && !err && (
        <p className="muted small">
          ⟳ Reconnecting… showing the last known status. Your analysis keeps running regardless.
        </p>
      )}
      {err && job && (
        <p className="error">
          {err}{" "}
          <button className="secondary" onClick={() => { setErr(null); setTick((t) => t + 1); }}>
            Try again
          </button>
        </p>
      )}

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
        <>
          <ol className="steps">
            {STEPS.map((s, i) => (
              <li key={s} className={i < stepIdx ? "done" : i === stepIdx ? "active" : ""}>{s}</li>
            ))}
          </ol>

          {isStoppable(job.status) && (
            <p>
              {confirmStop ? (
                <span className="confirm-inline">
                  Stop this analysis? Nothing is saved, and you can submit this kit again.
                  <button className="danger" disabled={busy} onClick={stop}>
                    {busy ? "Stopping…" : "Stop analysis"}
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => setConfirmStop(false)}>
                    Keep running
                  </button>
                </span>
              ) : (
                <button className="danger-link" onClick={() => setConfirmStop(true)}>
                  Stop analysis
                </button>
              )}
              {stopErr && <span className="error"> {stopErr}</span>}
            </p>
          )}
          {job.status === "uploading" && (
            <p className="muted small">Saving results — this analysis can no longer be stopped.</p>
          )}
        </>
      )}

      <h2>Sample batches</h2>
      <table className="table">
        <thead><tr><th>Batch</th><th>Species</th><th>Tags</th><th>Plate</th></tr></thead>
        <tbody>
          {job.batches.map((b) => (
            <tr key={b.id}>
              <td>{b.name}</td><td>{b.species || "—"}</td><td>{b.selected_tags.join(", ")}</td>
              <td>
                {job.status === "succeeded" ? (
                  <button className="linkish" onClick={() =>
                    api.downloadBatchPlate(job.public_id, b.id, `${b.name}_plate.xlsx`)}>
                    Download plate
                  </button>
                ) : <span className="muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {job.parameters && Object.keys(job.parameters).length > 0 && (
        <details className="card">
          <summary><b>Parameters</b> <span className="muted small">— pipeline settings this run used</span></summary>
          <table className="table">
            <tbody>
              {Object.entries(job.parameters).map(([k, v]) => (
                <tr key={k}><td className="mono small">{k}</td><td>{String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {job.status === "succeeded" && (
        <>
          {results.some((r) => !CONSENSUS_KINDS.includes(r.kind) && !HIDDEN_KINDS.includes(r.kind)) && (
            <div className="card">
              <h3>Results</h3>
              <ul className="results">
                {results
                  .filter((r) => !CONSENSUS_KINDS.includes(r.kind) && !HIDDEN_KINDS.includes(r.kind))
                  .map((r) => <ResultRow key={r.filename} r={r} />)}
              </ul>
            </div>
          )}

          {results.some((r) => CONSENSUS_KINDS.includes(r.kind)) && (
            <div className="card">
              <h3>Consensus <span className="muted small">(per-kit)</span></h3>
              <p className="muted small">Allele names in these files are assigned <b>per kit</b> from this
                run's read frequencies and may not match the project's allele names, which are curated per
                project. <code>allele_sequences.txt</code> lists the DNA sequence behind each name.</p>
              <ul className="results">
                {results.filter((r) => CONSENSUS_KINDS.includes(r.kind)).map((r) => (
                  <ResultRow key={r.filename} r={r} />
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h2>Assign to project <span className="muted small">(for consensus &amp; matching)</span></h2>
            <p className="muted small">Assign this run's samples to a project/population/study — no
              re-run. Pick a <b>population</b> to make the samples available for consensus and matching.</p>
            {kitStudy && !assignMsg && (
              <p className="muted small">Pre-filled from this kit's linked study <b>{kitStudy.name}</b>.</p>
            )}
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
                <p className="muted small">
                  ⚠️ Reanalysis re-runs this kit and <b>replaces</b> its previous samples and results in
                  the project — they aren't duplicated. Locked genotypes are kept; re-run matching afterward.
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
