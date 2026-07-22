import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useAuth } from "../auth.jsx";

export default function Home() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [projects, setProjects] = useState(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  return (
    <div className="container">
      <div className="banner">
        <h2>Welcome to STReamGT</h2>
        <p className="muted">
          Upload your kit’s FASTQ data, run genotyping, and download your results and QC
          reports. New here? Start with the guides.
        </p>
        <p className="row" style={{ gap: "1rem" }}>
          <Link to="/manuals/user">User Guide</Link>
          {isAdmin && <Link to="/manuals/admin">Admin Guide</Link>}
        </p>
      </div>

      <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
        <Link to="/submit"><button>New analysis</button></Link>
        <Link to="/kits"><button className="secondary">My kits &amp; analyses</button></Link>
      </div>

      <div className="section-head" style={{ marginTop: "1.8rem" }}>
        <h2>My projects</h2>
        <Link to="/projects">View all →</Link>
      </div>
      {projects === null ? (
        <p className="muted">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="muted">No projects yet. <Link to="/projects">Create your first project</Link>.</p>
      ) : (
        <div className="project-grid">
          {projects.slice(0, 8).map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="card project-card">
              <strong>{p.name}</strong>
              {p.organisation && <span className="muted small">{p.organisation}</span>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
