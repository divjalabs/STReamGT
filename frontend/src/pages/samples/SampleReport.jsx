import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { num } from "../../components/consensus.jsx";

// Samples in a population or a study: searchable list; a row opens the dedicated sample page.
export default function SampleReport() {
  const { populationId, studyId } = useParams();
  const nav = useNavigate();
  const [samples, setSamples] = useState(null);
  const [populations, setPopulations] = useState([]);
  const [studies, setStudies] = useState([]);
  const [title, setTitle] = useState("Sample report");
  const [query, setQuery] = useState("");
  const [err, setErr] = useState(null);

  const loadSamples = () =>
    (studyId ? api.listStudySamples(studyId) : api.listPopulationSamples(populationId))
      .then(setSamples).catch((e) => setErr(e.message));
  useEffect(() => { loadSamples(); }, [populationId, studyId]);

  useEffect(() => {
    // Populate the reassign dropdowns with the project's populations + studies; resolve the project
    // via the study (study mode) or the population (population mode).
    const project = studyId
      ? api.getStudy(studyId).then((s) => { setTitle(`Samples · ${s.name}`); return s.project_id; })
      : api.getPopulation(populationId).then((p) => p.project_id);
    project.then((pid) => Promise.all([api.listPopulations(pid), api.listStudies(pid)]))
      .then(([pops, sts]) => { setPopulations(pops); setStudies(sts); })
      .catch((e) => setErr(e.message));
  }, [populationId, studyId]);

  const assign = async (sampleId, newPopId) => {
    setErr(null);
    try { await api.patchSample(sampleId, { population_id: Number(newPopId) }); await loadSamples(); }
    catch (e) { setErr(e.message); }
  };
  const assignStudy = async (sampleId, newStudyId) => {
    setErr(null);
    try {
      await api.patchSample(sampleId, { study_id: newStudyId ? Number(newStudyId) : null });
      await loadSamples();
    } catch (e) { setErr(e.message); }
  };

  const filtered = useMemo(() => {
    if (!samples) return null;
    const q = query.trim().toLowerCase();
    if (!q) return samples;
    return samples.filter((s) =>
      s.name.toLowerCase().includes(q) || s.system_code.toLowerCase().includes(q));
  }, [samples, query]);

  return (
    <div className="container">
      <h1>{title}</h1>
      {err && <p className="error">{err}</p>}
      <input className="search" type="search" placeholder="Search samples by name or ID…"
             value={query} onChange={(e) => setQuery(e.target.value)} />

      {!filtered ? <p>Loading…</p> : samples.length === 0 ? (
        <p className="muted">No samples {studyId ? "in this study" : "in this population"} yet. Run a job that targets this project.</p>
      ) : filtered.length === 0 ? (
        <p className="muted">No samples match “{query}”.</p>
      ) : (
        <table className="table">
          <thead>
            <tr><th>System ID</th><th>Name</th><th>Sex</th><th>Genotyped OK</th><th>QI</th>
              <th>Animal</th><th>Population</th><th>Study</th></tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id} className={s.discard_sample ? "discarded" : ""}
                  style={{ cursor: "pointer" }} onClick={() => nav(`/samples/${s.id}`)}>
                <td>{s.system_code}{s.discard_sample && <span className="tag">discarded</span>}</td>
                <td>{s.name}</td><td>{s.sex}</td>
                <td>{s.genotype_ok ? "yes" : "—"}</td><td>{num(s.quality_index)}</td>
                <td className="muted" onClick={(e) => e.stopPropagation()}>
                  {s.subgroup_id ? <Link to={`/animals/${s.subgroup_id}`}>#{s.subgroup_id}</Link> : "—"}
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  <select className="pop-select" value={s.population_id ?? ""}
                          onChange={(e) => assign(s.id, e.target.value)}>
                    {populations.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  <select className="pop-select" value={s.study_id ?? ""}
                          onChange={(e) => assignStudy(s.id, e.target.value)}>
                    <option value="">— none —</option>
                    {studies
                      .filter((st) => st.population_id === s.population_id || st.id === s.study_id)
                      .map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
