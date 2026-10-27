import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { MatchingSettingsForm } from "../../components/MatchingSettings.jsx";

// Individual animal (subgroup) page. The animal's matches + per-locus genotype grid are shown
// inline. "Rerun matching" opens a dialog of matching settings; running it re-matches this animal's
// reference against the population and updates the page.
export default function AnimalView() {
  const { subgroupId } = useParams();
  const [animal, setAnimal] = useState(null);
  const [result, setResult] = useState(null);      // { matches, genotypes }
  const [settings, setSettings] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(false);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const guard = (fn) => async (...a) => {
    setErr(null); setBusy(true);
    try { return await fn(...a); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const load = guard(async () => {
    const a = await api.getSubgroup(subgroupId);
    setAnimal(a);
    setResult(await api.rematchSubgroup(subgroupId));
  });
  useEffect(() => { load(); }, [subgroupId]);

  const patch = guard(async (body) => { await api.patchSubgroup(subgroupId, body); await load(); });
  const changeRef = guard(async (sid) => {
    await api.patchSubgroup(subgroupId, { reference_sample_id: sid });
    await load();
  });

  const openSettings = guard(async () => {
    if (animal) setSettings(await api.getMatchingSettings(animal.population_id));
    setSettingsOpen(true);
  });
  const runRematch = guard(async (s) => {
    await api.putMatchingSettings(animal.population_id, s);   // rematch uses the population settings
    setResult(await api.rematchSubgroup(subgroupId));
    setAnimal(await api.getSubgroup(subgroupId));             // reliable/total may change
    setSettingsOpen(false);
  });

  if (err && !animal) return <div className="container"><p className="error">{err}</p></div>;
  if (!animal) return <div className="container"><p>Loading…</p></div>;

  const memberIds = new Set(animal.members.map((m) => m.id));
  const matches = result?.matches ?? [];
  const candidates = matches.filter((m) => !m.is_reference);

  return (
    <div className="container">
      <p><Link to={`/populations/${animal.population_id}/match`}>← Animals</Link></p>
      <div className="report-head">
        <h1>Animal <span className="muted">{animal.label || `#${animal.id}`}</span></h1>
        <button onClick={openSettings} disabled={busy}>Rerun matching</button>
      </div>
      {err && <p className="error">{err}</p>}

      <div className="animal-head">
        <label className="check-inline">
          <input type="checkbox" checked={animal.reliably_genotyped} disabled={busy}
                 onChange={(e) => patch({ reliably_genotyped: e.target.checked })} />
          Reliably genotyped
        </label>
        <label className="info-field">Reference (Ref)
          <select value={animal.reference_sample_id ?? ""} disabled={busy}
                  onChange={(e) => changeRef(Number(e.target.value))}>
            {animal.members.map((m) => <option key={m.id} value={m.id}>{m.system_code}</option>)}
          </select>
        </label>
        <span className="info-field">Reliable matches <strong>{animal.n_reliable}</strong></span>
        <span className="info-field">Total samples <strong>{animal.n_samples}</strong></span>
      </div>

      <h2>Matches ({candidates.length})</h2>
      {result === null ? <p className="muted">Loading…</p> : matches.length === 0 ? (
        <p className="muted">No matches. Try “Rerun matching”.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Sample</th><th>Loci</th><th>ADO</th><th>1IC</th><th>2IC</th><th>Total</th>
                <th>Match</th><th>Mismatches (per locus)</th><th></th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m) => (
                <tr key={m.sample_id}
                    className={m.is_reference ? "ref-row" : m.reliable ? "reliable-row" : ""}>
                  <td>
                    <Link to={`/samples/${m.sample_id}`}>{m.system_code}</Link>
                    {m.is_reference && <span className="tag">ref</span>}
                  </td>
                  <td>{m.loci_matched}</td>
                  <td>{m.num_ado_mm}</td><td>{m.num_1ic}</td><td>{m.num_2ic}</td>
                  <td>{m.num_total_ic}</td>
                  <td>
                    <span className={`badge ${m.is_reference || m.reliable ? "ok" : "warn"}`}>
                      {m.is_reference ? "reference" : m.reliable ? "reliable" : "possible"}
                    </span>
                  </td>
                  <td className="muted small">
                    {m.mismatches.length ? m.mismatches.map((x) => `${x.marker}:${x.code}`).join(", ") : "—"}
                  </td>
                  <td>
                    {!m.is_reference && memberIds.has(m.sample_id) && (
                      <button className="secondary" disabled={busy}
                              onClick={() => changeRef(m.sample_id)}>Set ref</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {matches.length > 0 && (
        <div className="actions">
          <button className="secondary" onClick={() => setShowGrid((v) => !v)}>
            {showGrid ? "Hide genotypes" : "Show genotypes per locus"}
          </button>
        </div>
      )}
      {showGrid && result && <GenotypeGrid grid={result.genotypes} matches={matches} />}

      {settingsOpen && (
        <div className="modal-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="modal-panel modal-narrow" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h2>Rerun matching</h2>
              <button className="linkbtn" onClick={() => setSettingsOpen(false)} title="Close">✕</button>
            </div>
            <p className="muted small">Adjust the matching thresholds, then run — the animal’s matches
              update with the new settings.</p>
            {settings
              ? <MatchingSettingsForm settings={settings} onSave={runRematch} busy={busy}
                                      title={null} saveLabel="Run rematch" />
              : <p className="muted">Loading settings…</p>}
          </div>
        </div>
      )}
    </div>
  );
}

// Per-locus genotype comparison: markers (rows) × samples (columns); reference column marked,
// cells tinted where the sample mismatches the reference.
function GenotypeGrid({ grid, matches }) {
  const codeOf = Object.fromEntries(matches.map((m) => [m.sample_id, m.system_code]));
  return (
    <div className="table-scroll" style={{ marginTop: ".5rem" }}>
      <table className="table genotype-grid">
        <thead>
          <tr>
            <th>Marker</th>
            {grid.samples.map((s) => (
              <th key={s.sample_id} className={s.is_reference ? "ref-col" : ""}>
                {codeOf[s.sample_id] || s.sample_id}{s.is_reference && " ★"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.markers.map((mk) => (
            <tr key={mk}>
              <td className="marker-cell">{mk}</td>
              {grid.samples.map((s) => {
                const cell = s.cells[mk] || {};
                const cls = cell.mismatch ? "cell-mismatch" : s.is_reference ? "ref-col" : "";
                return <td key={s.sample_id} className={cls}>{cell.call || "—"}</td>;
              })}
            </tr>
          ))}
          {grid.markers.length === 0 && (
            <tr><td className="muted" colSpan={grid.samples.length + 1}>No genotypes.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
