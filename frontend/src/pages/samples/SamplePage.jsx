import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { ConsensusTable, ReplicateTable, num } from "../../components/consensus.jsx";
import { GenotypePlot } from "../../components/GenotypePlot.jsx";

// Full-width per-sample workspace: filter/navigate the sample set, reassign, edit consensus, and
// inspect plots/replicates in a resizable side panel.
export default function SamplePage() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sample, setSample] = useState(null);
  const [plots, setPlots] = useState(null);
  const [replicates, setReplicates] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // filter/nav option lists
  const [pops, setPops] = useState([]);
  const [studyList, setStudyList] = useState([]);
  const [kits, setKits] = useState([]);
  // filter state (navigation, NOT reassignment)
  const [fPop, setFPop] = useState("");
  const [fStudy, setFStudy] = useState("");
  const [fKit, setFKit] = useState("");
  const [nameQuery, setNameQuery] = useState("");
  const [nameOpen, setNameOpen] = useState(false);
  const [catSamples, setCatSamples] = useState([]);
  const filtersInit = useRef(false);

  // right panel
  const [panelTab, setPanelTab] = useState("plots");
  const [panelHidden, setPanelHidden] = useState(false);
  const [panelWidth, setPanelWidth] = useState(38);
  const bodyRef = useRef(null);
  const resizing = useRef(false);

  const markers = useMemo(() => (sample ? sample.consensus.map((c) => c.marker) : []), [sample]);

  const load = async () => {
    setErr(null);
    try {
      const d = await api.getSample(id);
      setSample(d);
      setSelected((prev) => (prev.size ? prev : new Set(d.consensus.map((c) => c.marker))));
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => { setPlots(null); setReplicates(null); load(); }, [id]);

  // filter option lists
  useEffect(() => {
    if (!sample?.project_id) return;
    api.listPopulations(sample.project_id).then(setPops).catch(() => {});
    api.listStudies(sample.project_id).then(setStudyList).catch(() => {});
    api.listKits().then(setKits).catch(() => {});
  }, [sample?.project_id]);

  // prefill the filters from the first sample loaded
  useEffect(() => {
    if (sample && !filtersInit.current) {
      setFPop(sample.population_id ? String(sample.population_id) : "");
      setFStudy(sample.study_id ? String(sample.study_id) : "");
      setFKit(sample.kit_id ? String(sample.kit_id) : "");
      filtersInit.current = true;
    }
  }, [sample]);

  // navigable "category" set — precedence: study > kit > population > all
  useEffect(() => {
    if (!sample?.project_id) return;
    const pid = sample.project_id;
    let p;
    if (fStudy) p = api.listStudySamples(fStudy);
    else if (fKit) p = api.listKitSamples(fKit);
    else if (fPop) p = api.listPopulationSamples(fPop);
    else p = api.listProjectSamples(pid);
    p.then((rows) => setCatSamples(rows.filter((r) => r.project_id === pid))).catch(() => setCatSamples([]));
  }, [fStudy, fKit, fPop, sample?.project_id]);

  const navSet = useMemo(() => {
    const q = nameQuery.trim().toLowerCase();
    return q ? catSamples.filter((s) =>
      s.name.toLowerCase().includes(q) || s.system_code.toLowerCase().includes(q)) : catSamples;
  }, [catSamples, nameQuery]);
  const idx = navSet.findIndex((s) => String(s.id) === String(id));
  const go = (i) => { if (navSet[i]) { nav(`/samples/${navSet[i].id}`); setNameOpen(false); } };

  const guard = (fn) => async (...a) => {
    setErr(null); setBusy(true);
    try { await fn(...a); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const patch = guard(async (body) => {
    const u = await api.patchSample(id, body);
    setSample((d) => ({ ...d, ...u }));
  });
  // Serialize consensus mutations so an in-flight cell edit (committed on blur) always lands
  // BEFORE a lock/rerun fired by the same click — otherwise locking first makes the edit 409.
  const mutChain = useRef(Promise.resolve());
  const mutate = (fn) => {
    const p = mutChain.current.then(async () => {
      setErr(null); setBusy(true);
      try { await fn(); await load(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
    });
    mutChain.current = p.catch(() => {});
    return p;
  };
  const editCell = (cid, body) => mutate(() => api.editConsensus(cid, body));
  const toggleLock = (c) => mutate(() => (c.is_locked ? api.unlockConsensus(c.id) : api.lockConsensus(c.id)));
  const rerun = () => mutate(async () => { await api.rerunSampleConsensus(id); setPlots(null); setReplicates(null); });

  // lazy-load the active panel's data
  useEffect(() => {
    if (panelHidden || !sample) return;
    if (panelTab === "plots" && plots === null)
      api.getSamplePlotData(id, []).then(setPlots).catch((e) => setErr(e.message));
    if (panelTab === "replicates" && replicates === null)
      api.getSampleReplicates(id).then(setReplicates).catch((e) => setErr(e.message));
  }, [panelTab, panelHidden, plots, replicates, id, sample]);

  // draggable divider
  const startResize = (e) => { resizing.current = true; e.preventDefault(); };
  useEffect(() => {
    const move = (e) => {
      if (!resizing.current || !bodyRef.current) return;
      const rect = bodyRef.current.getBoundingClientRect();
      const pct = ((rect.right - e.clientX) / rect.width) * 100;
      setPanelWidth(Math.min(70, Math.max(20, pct)));
    };
    const up = () => { resizing.current = false; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, []);

  const allSelected = selected.size === markers.length && markers.length > 0;
  const toggleMarker = (m) =>
    setSelected((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n; });
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(markers));

  if (err && !sample) return <div className="sample-fullwidth"><p className="error">{err}</p></div>;
  if (!sample) return <div className="sample-fullwidth"><p>Loading…</p></div>;

  const catName = fStudy ? "study" : fKit ? "kit" : fPop ? "population" : "all samples";

  return (
    <div className="sample-fullwidth">
      <p><Link to={sample.population_id ? `/populations/${sample.population_id}/samples` : "/projects"}>← Samples</Link></p>

      <div className="sample-head">
        <div className="sample-head-left">
          <div className="sample-nav">
          <button className="secondary navarrow" disabled={idx <= 0} onClick={() => go(idx - 1)}>‹</button>
          <div className="name-search">
            <input className="name-input" value={nameQuery}
                   placeholder={`${sample.name} · ${sample.system_code}`}
                   onChange={(e) => { setNameQuery(e.target.value); setNameOpen(true); }}
                   onFocus={() => setNameOpen(true)}
                   onBlur={() => setTimeout(() => setNameOpen(false), 150)} />
            {nameOpen && navSet.length > 0 && (
              <ul className="name-dropdown">
                {navSet.slice(0, 40).map((s) => (
                  <li key={s.id} className={String(s.id) === String(id) ? "cur" : ""}
                      onMouseDown={() => go(navSet.indexOf(s))}>
                    {s.system_code} · {s.name}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button className="secondary navarrow" disabled={idx < 0 || idx >= navSet.length - 1}
                  onClick={() => go(idx + 1)}>›</button>
          <span className="muted small">{idx >= 0 ? `${idx + 1} / ${navSet.length}` : `${navSet.length}`}</span>
          </div>
          <h1 className="sample-title">{sample.name} <span className="muted">· {sample.system_code}</span></h1>
        </div>

        <fieldset className="filters-frame">
          <legend>select</legend>
          <label>Population
            <select value={fPop} onChange={(e) => setFPop(e.target.value)}>
              <option value="">any</option>
              {pops.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label>Study
            <select value={fStudy} onChange={(e) => setFStudy(e.target.value)}>
              <option value="">any</option>
              {studyList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label>Kit
            <select value={fKit} onChange={(e) => setFKit(e.target.value)}>
              <option value="">any</option>
              {kits.map((k) => <option key={k.id} value={k.id}>{k.kit_code}</option>)}
            </select>
          </label>
          <label>Sample name
            <input value={nameQuery} onChange={(e) => setNameQuery(e.target.value)} placeholder="filter by name" />
          </label>
          <p className="muted small filters-note">Browsing {navSet.length} sample(s) from <strong>{catName}</strong>.</p>
        </fieldset>
      </div>
      {err && <p className="error">{err}</p>}

      <div className="reassign-bar">
        <span className="reassign-label">Reassign this sample to:</span>
        <label className="qc-field">Population
          <select value={sample.population_id ?? ""} disabled={busy}
                  onChange={(e) => e.target.value && patch({ population_id: Number(e.target.value) })}>
            {pops.length === 0 && <option value="">—</option>}
            {pops.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="qc-field">Study
          <select value={sample.study_id ?? ""} disabled={busy}
                  onChange={(e) => patch({ study_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">— none —</option>
            {studyList.filter((s) => s.population_id === sample.population_id || s.id === sample.study_id)
              .map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
      </div>

      <div className="info-bar">
        <button className={`stat-badge ${sample.genotype_ok ? "good" : "bad"}`}
                onClick={() => patch({ genotype_ok: !sample.genotype_ok })} title="Click to toggle">
          {sample.genotype_ok ? "✓ Genotyped" : "✕ Not genotyped"}
        </button>
        <span className={`stat-badge ${sample.subgroup_id ? "good" : "neutral"}`}>
          {sample.subgroup_id ? `✓ Matched${sample.animal_label ? ` · ${sample.animal_label}` : ""}` : "Unmatched"}
        </span>
        <span className="info-field">Kit <strong>{sample.kit_code || "—"}</strong></span>
        <span className="info-field">Animal <strong>{sample.animal_label || "—"}</strong></span>
        <span className="muted small">mean QI {num(sample.quality_index)} · {sample.n_replicates ?? "—"} reps</span>
        <label className="qc-field">Sex
          <select value={sample.sex} onChange={(e) => patch({ sex: e.target.value })}>
            <option value="unknown">unknown</option>
            <option value="male">male</option>
            <option value="female">female</option>
          </select>
        </label>
        {sample.sex_locked && (
          <button className="linkbtn" title="Unlock sex" onClick={() => patch({ sex_locked: false })}>🔒 unlock</button>
        )}
        <label className="qc-field check">
          <input type="checkbox" checked={sample.discard_sample}
                 onChange={(e) => patch({ discard_sample: e.target.checked })} />
          Discard (exclude from matching)
        </label>
      </div>

      <div className="actions">
        <button onClick={rerun} disabled={busy}>Rerun consensus</button>
        <button className="secondary" disabled={!sample.population_id}
                onClick={() => nav(`/populations/${sample.population_id}/match`)}>Run match →</button>
        {panelHidden && <button className="secondary" onClick={() => setPanelHidden(false)}>Show plots / replicates ▸</button>}
      </div>

      {markers.length > 0 && (
        <div className="marker-chips">
          <span className="muted">Markers:</span>
          <button className={`chip-btn ${allSelected ? "on" : ""}`} onClick={toggleAll}>All</button>
          {markers.map((m) => (
            <button key={m} className={`chip-btn ${selected.has(m) ? "on" : ""}`} onClick={() => toggleMarker(m)}>{m}</button>
          ))}
        </div>
      )}

      <div className="sample-body" ref={bodyRef}>
        <div className="sample-main">
          <h2>Consensus</h2>
          {sample.consensus.length === 0
            ? <p className="muted">No consensus genotypes. Try “Rerun consensus”.</p>
            : <ConsensusTable rows={sample.consensus} onEdit={editCell} onToggleLock={toggleLock}
                              sex={sample.sex} onSetSex={(v) => patch({ sex: v })} sexMarker={sample.sex_marker} />}
        </div>
        {!panelHidden && (
          <>
            <div className="resizer" onMouseDown={startResize} title="Drag to resize" />
            <aside className="sample-panel" style={{ flexBasis: `${panelWidth}%` }}>
              <div className="panel-head">
                <div className="tabs">
                  <button className={panelTab === "plots" ? "active" : ""} onClick={() => setPanelTab("plots")}>Plots</button>
                  <button className={panelTab === "replicates" ? "active" : ""} onClick={() => setPanelTab("replicates")}>Replicates</button>
                </div>
                <div className="panel-actions">
                  <a className="linkbtn" href={`/samples/${id}/${panelTab}`} target="_blank" rel="noreferrer" title="Open in new tab">⧉</a>
                  <button className="linkbtn" onClick={() => setPanelHidden(true)} title="Hide panel">✕</button>
                </div>
              </div>
              <div className="panel-body">
                {panelTab === "plots" ? (
                  plots === null ? <p className="muted">Loading…</p>
                    : plots.length === 0 ? <p className="muted">No plot data.</p>
                    : <div className="plot-grid">
                        {plots.filter((p) => selected.has(p.marker)).map((p) => (
                          <GenotypePlot key={p.marker} plot={p}
                            subtitle={p.marker === sample.sex_marker ? `sex: ${sample.sex}` : undefined} />
                        ))}
                      </div>
                ) : (
                  replicates === null ? <p className="muted">Loading…</p>
                    : (() => {
                        const rows = replicates.filter((r) => selected.has(r.marker));
                        return rows.length === 0
                          ? <p className="muted">Select markers to show replicates.</p>
                          : <ReplicateTable rows={rows} />;
                      })()
                )}
              </div>
            </aside>
          </>
        )}
      </div>
    </div>
  );
}
