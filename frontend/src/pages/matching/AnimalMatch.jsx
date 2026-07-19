import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { MatchingSettingsForm } from "../../components/MatchingSettings.jsx";

export default function AnimalMatch() {
  const { populationId } = useParams();
  const [samples, setSamples] = useState([]);
  const [subgroups, setSubgroups] = useState([]);
  const [supergroups, setSupergroups] = useState([]);
  const [settings, setSettings] = useState(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    setErr(null);
    try {
      const [smp, subs, sups, set] = await Promise.all([
        api.listPopulationSamples(populationId), api.listSubgroups(populationId),
        api.listSupergroups(populationId), api.getMatchingSettings(populationId),
      ]);
      setSamples(smp); setSubgroups(subs); setSupergroups(sups); setSettings(set);
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); }, [populationId]);

  const byId = Object.fromEntries(samples.map((s) => [s.id, s]));
  const name = (id) => byId[id]?.system_code || `#${id}`;
  const membersOf = (sgId) => samples.filter((s) => s.subgroup_id === sgId);
  const sgLabel = (sgId) => subgroups.find((s) => s.id === sgId)?.label || `#${sgId}`;

  const q = query.trim().toLowerCase();
  const shownSubs = !q ? subgroups : subgroups.filter((sg) =>
    (sg.label || "").toLowerCase().includes(q) ||
    membersOf(sg.id).some((s) => s.system_code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)));

  const guard = (fn) => async (...a) => {
    setErr(null); setMsg(null); setBusy(true);
    try { await fn(...a); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const rerun = guard(async () => {
    const run = await api.rerunMatch(populationId);
    setMsg(`Grouped ${run.n_samples} samples into ${run.n_subgroups} animals.`);
    await load();
  });
  const saveSettings = guard(async (s) => { await api.putMatchingSettings(populationId, s); setMsg("Settings saved."); await load(); });

  return (
    <div className="container">
      <div className="report-head">
        <h1>Animal matching</h1>
        <button onClick={rerun} disabled={busy}>Rerun matching</button>
      </div>
      {err && <p className="error">{err}</p>}
      {msg && <p className="ok">{msg}</p>}

      {settings && <MatchingSettingsForm settings={settings} onSave={saveSettings} busy={busy} />}

      <input className="search" type="search" placeholder="Search samples by name or ID…"
             value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginTop: "1.2rem" }} />

      <h2 style={{ marginTop: "1rem" }}>Animals ({shownSubs.length})</h2>
      {shownSubs.length === 0 ? (
        <p className="muted">{subgroups.length === 0
          ? "No animals yet. Run matching to group samples into individuals."
          : `No animals match “${query}”.`}</p>
      ) : (
        <table className="table">
          <thead><tr><th>Animal</th><th>Samples</th><th>Reliable</th><th>Reference</th><th>Members</th></tr></thead>
          <tbody>
            {shownSubs.map((sg) => (
              <tr key={sg.id}>
                <td><Link to={`/animals/${sg.id}`}>{sg.label || `#${sg.id}`}</Link></td>
                <td>{sg.n_samples}</td>
                <td>{sg.reliably_genotyped ? <span className="badge ok">yes</span> : <span className="muted">—</span>}</td>
                <td className="muted">{sg.reference_sample_id ? name(sg.reference_sample_id) : "—"}</td>
                <td className="muted">{membersOf(sg.id).map((s) => s.system_code).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {supergroups.length > 0 && (
        <>
          <h2 style={{ marginTop: "1.5rem" }}>⚠ Supergroups — QC ({supergroups.length})</h2>
          <p className="muted small">Animals linked by reliable cross-matches — possibly the same
            individual or a genotyping error. Review before treating them as distinct.</p>
          <table className="table">
            <thead><tr><th>Supergroup</th><th>Linked animals</th></tr></thead>
            <tbody>
              {supergroups.map((sg) => (
                <tr key={sg.id} className="flagged">
                  <td>{sg.label || `#${sg.id}`}</td>
                  <td>{sg.subgroup_ids.map(sgLabel).join("  ·  ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

    </div>
  );
}
