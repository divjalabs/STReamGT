import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client.js";

const TIER_CLASS = { reliable: "ok", possible: "warn", none: "muted" };

function SettingsPanel({ settings, onSave, busy }) {
  const [s, setS] = useState(settings);
  useEffect(() => setS(settings), [settings]);
  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));
  const numField = (k, label) => (
    <label className="field">
      <span>{label}</span>
      <input type="number" step="any" value={s[k]} onChange={(e) => set(k, Number(e.target.value))} />
    </label>
  );
  return (
    <div className="card settings-card">
      <h3>Matching settings</h3>
      <div className="fields">
        {numField("min_shared_loci", "Min shared loci")}
        <label className="field">
          <span>Mismatch metric</span>
          <select value={s.mismatch_metric} onChange={(e) => set("mismatch_metric", e.target.value)}>
            <option value="decomposed">decomposed (ADO/IC)</option>
            <option value="flat">flat (Tm)</option>
          </select>
        </label>
        <label className="field check">
          <input type="checkbox" checked={s.use_pi_gate} onChange={(e) => set("use_pi_gate", e.target.checked)} />
          <span>Use PI/PIsib gate</span>
        </label>
        {s.mismatch_metric === "flat" ? (
          <>{numField("tm_possible", "Tm possible")}{numField("tm_reliable", "Tm reliable")}</>
        ) : (
          <>
            {numField("max_ado_mm_match", "Max ADO (possible)")}
            {numField("max_total_mm_match", "Max total IC (possible)")}
            {numField("reliable_max_ado_mm", "Max ADO (reliable)")}
            {numField("reliable_max_total", "Max total IC (reliable)")}
          </>
        )}
      </div>
      <button onClick={() => onSave(s)} disabled={busy}>Save settings</button>
    </div>
  );
}

export default function AnimalMatch() {
  const { populationId } = useParams();
  const [samples, setSamples] = useState([]);
  const [subgroups, setSubgroups] = useState([]);
  const [supergroups, setSupergroups] = useState([]);
  const [matches, setMatches] = useState([]);
  const [settings, setSettings] = useState(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    setErr(null);
    try {
      const [smp, subs, sups, mts, set] = await Promise.all([
        api.listPopulationSamples(populationId), api.listSubgroups(populationId),
        api.listSupergroups(populationId), api.listMatches(populationId),
        api.getMatchingSettings(populationId),
      ]);
      setSamples(smp); setSubgroups(subs); setSupergroups(sups); setMatches(mts); setSettings(set);
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); }, [populationId]);

  const byId = Object.fromEntries(samples.map((s) => [s.id, s]));
  const name = (id) => byId[id]?.system_code || `#${id}`;
  const membersOf = (sgId) => samples.filter((s) => s.subgroup_id === sgId);
  const sgLabel = (sgId) => subgroups.find((s) => s.id === sgId)?.label || `#${sgId}`;

  const q = query.trim().toLowerCase();
  const hitSample = (id) => {
    const s = byId[id];
    return s && (s.system_code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
  };
  const shownSubs = !q ? subgroups : subgroups.filter((sg) =>
    (sg.label || "").toLowerCase().includes(q) ||
    membersOf(sg.id).some((s) => s.system_code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)));
  const shownMatches = !q ? matches
    : matches.filter((m) => hitSample(m.sample_a_id) || hitSample(m.sample_b_id));

  const guard = (fn) => async (...a) => {
    setErr(null); setMsg(null); setBusy(true);
    try { await fn(...a); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const rerun = guard(async () => {
    const run = await api.rerunMatch(populationId);
    setMsg(`Matched ${run.n_samples} samples → ${run.n_subgroups} animals (${run.n_matches} matches).`);
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

      {settings && <SettingsPanel settings={settings} onSave={saveSettings} busy={busy} />}

      <input className="search" type="search" placeholder="Search samples by name or ID…"
             value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginTop: "1.2rem" }} />

      <h2 style={{ marginTop: "1rem" }}>Animals ({shownSubs.length})</h2>
      {shownSubs.length === 0 ? (
        <p className="muted">{subgroups.length === 0
          ? "No animals yet. Run matching to group samples into individuals."
          : `No animals match “${query}”.`}</p>
      ) : (
        <table className="table">
          <thead><tr><th>Animal</th><th>Samples</th><th>Reference</th><th>Members</th></tr></thead>
          <tbody>
            {shownSubs.map((sg) => (
              <tr key={sg.id}>
                <td>{sg.label || `#${sg.id}`}</td>
                <td>{sg.n_samples}</td>
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

      <h2 style={{ marginTop: "1.5rem" }}>Matches ({shownMatches.length})</h2>
      {shownMatches.length === 0 ? (
        <p className="muted">No matches.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr><th>Sample A</th><th>Sample B</th><th>Tier</th><th>Loci</th>
                <th>ADO</th><th>1IC</th><th>2IC</th><th>Flat</th><th>dPI</th></tr>
            </thead>
            <tbody>
              {shownMatches.map((m, i) => (
                <tr key={i}>
                  <td>{name(m.sample_a_id)}</td><td>{name(m.sample_b_id)}</td>
                  <td><span className={`badge ${TIER_CLASS[m.tier]}`}>{m.tier}</span></td>
                  <td>{m.loci_matched}</td>
                  <td>{m.num_ado_mm}</td><td>{m.num_1ic}</td><td>{m.num_2ic}</td>
                  <td>{m.flat_mismatch}</td>
                  <td>{m.d_pi != null ? Number(m.d_pi).toExponential(1) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
