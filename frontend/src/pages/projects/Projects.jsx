import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";

export default function Projects() {
  const [projects, setProjects] = useState(null);
  const [err, setErr] = useState(null);
  const [name, setName] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [species, setSpecies] = useState("");
  const [speciesOpts, setSpeciesOpts] = useState([]);

  const load = () => api.listProjects().then(setProjects).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listKits()
      .then((kits) => setSpeciesOpts([...new Set(kits.map((k) => k.species).filter(Boolean))].sort()))
      .catch(() => {});
  }, []);

  const create = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await api.createProject({ name, organisation: organisation || null, species: species || null });
      setName(""); setOrganisation(""); setSpecies("");
      load();
    } catch (e2) { setErr(e2.message); }
  };

  const importJson = async (file) => {
    setErr(null);
    try { const p = await api.importProjectJson(file); await load(); }
    catch (e2) { setErr(e2.message); }
  };

  return (
    <div className="container">
      <h1>Projects</h1>
      <p className="muted">
        A project holds samples, animals, and matching, aggregated across kits. Consensus results
        from a job are ingested here when the job targets a project.
      </p>
      {err && <p className="error">{err}</p>}

      <form className="card" onSubmit={create} style={{ marginBottom: "1rem" }}>
        <h3>New project</h3>
        <div className="row">
          <input placeholder="Project name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Organisation (optional)" value={organisation} onChange={(e) => setOrganisation(e.target.value)} />
          <select value={species} onChange={(e) => setSpecies(e.target.value)}
                  title="A project holds one species; leave blank to set it from the first kit assigned">
            <option value="">Species — set from first kit</option>
            {speciesOpts.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button type="submit">Create</button>
        </div>
        <div className="row" style={{ marginTop: ".5rem" }}>
          <span className="muted small">or import a project export:</span>
          <input type="file" accept=".json,application/json" onChange={(e) => {
            const f = e.target.files[0]; if (f) importJson(f); e.target.value = "";
          }} />
        </div>
      </form>

      {!projects ? (
        <p>Loading…</p>
      ) : projects.length === 0 ? (
        <p className="muted">No projects yet.</p>
      ) : (
        <table className="table">
          <thead><tr><th>Name</th><th>Organisation</th><th>Created</th></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/projects/${p.id}`}>{p.name}</Link></td>
                <td className="muted">{p.organisation || "—"}</td>
                <td className="muted">{new Date(p.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
