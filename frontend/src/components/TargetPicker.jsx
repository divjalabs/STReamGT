import { useEffect, useState } from "react";
import { api } from "../api/client.js";

// Cascading Project → Population → Study selector for a job's ingestion target. All optional.
// value = { project_id, default_population_id, default_study_id }; onChange gets the same shape.
export default function TargetPicker({ value, onChange, disabled }) {
  const [projects, setProjects] = useState([]);
  const [pops, setPops] = useState([]);
  const [studies, setStudies] = useState([]);
  const { project_id, default_population_id, default_study_id } = value;

  useEffect(() => { api.listProjects().then(setProjects).catch(() => {}); }, []);
  useEffect(() => {
    if (!project_id) { setPops([]); setStudies([]); return; }
    api.listPopulations(project_id).then(setPops).catch(() => setPops([]));
    api.listStudies(project_id).then(setStudies).catch(() => setStudies([]));
  }, [project_id]);

  const num = (v) => (v ? Number(v) : null);
  const setProject = (v) => onChange({ project_id: num(v), default_population_id: null, default_study_id: null });
  const setPop = (v) => onChange({ ...value, default_population_id: num(v), default_study_id: null });
  const setStudy = (v) => {
    const st = studies.find((s) => String(s.id) === String(v));
    onChange({
      ...value, default_study_id: num(v),
      default_population_id: st && st.population_id ? st.population_id : default_population_id,
    });
  };

  const shownStudies = default_population_id
    ? studies.filter((s) => s.population_id === default_population_id || s.id === default_study_id)
    : studies;

  return (
    <div className="target-picker">
      <label>Project
        <select value={project_id ?? ""} disabled={disabled} onChange={(e) => setProject(e.target.value)}>
          <option value="">— none —</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label>Population
        <select value={default_population_id ?? ""} disabled={disabled || !project_id}
                onChange={(e) => setPop(e.target.value)}>
          <option value="">— none —</option>
          {pops.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label>Study
        <select value={default_study_id ?? ""} disabled={disabled || !project_id}
                onChange={(e) => setStudy(e.target.value)}>
          <option value="">— none —</option>
          {shownStudies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
    </div>
  );
}
