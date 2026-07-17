import { useEffect, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api, downloadExport } from "../../api/client.js";
import { useAuth } from "../../auth.jsx";

const EXPORTS = [
  ["genotypes", "Genotypes CSV"],
  ["metadata", "Metadata CSV"],
  ["animals", "Animals CSV"],
  ["genepop", "GenePop"],
  ["json", "Project JSON"],
];

export default function ProjectDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const fileRef = useRef(null);
  const [project, setProject] = useState(null);
  const [populations, setPopulations] = useState([]);
  const [studies, setStudies] = useState([]);
  const [kits, setKits] = useState([]);
  const [access, setAccess] = useState(null);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [popName, setPopName] = useState("");
  const [addStudyFor, setAddStudyFor] = useState(null);
  const [newStudyName, setNewStudyName] = useState("");
  const [delStudy, setDelStudy] = useState(null);   // study id pending delete-confirm
  const [delPop, setDelPop] = useState(null);       // population id pending delete-confirm
  const [delTarget, setDelTarget] = useState("");   // reassign_to selection
  const [exportOpen, setExportOpen] = useState(false);
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState("viewer");
  const [confirming, setConfirming] = useState(false);
  const [confirmName, setConfirmName] = useState("");

  const load = () => {
    api.getProject(id).then(setProject).catch((e) => setErr(e.message));
    api.listPopulations(id).then(setPopulations).catch(() => {});
    api.listStudies(id).then(setStudies).catch(() => {});
    api.listProjectAccess(id).then(setAccess).catch(() => {});
    api.listKits().then(setKits).catch(() => {});
  };
  useEffect(() => { load(); }, [id]);

  const act = async (fn) => {
    setErr(null); setMsg(null);
    try { await fn(); load(); } catch (e) { setErr(e.message); }
  };
  const wrap = (fn) => (e) => { e.preventDefault(); act(fn); };

  const addPop = wrap(async () => { await api.createPopulation(id, { name: popName }); setPopName(""); });
  const addStudy = (e, popId) => {
    e.preventDefault();
    act(async () => {
      await api.createStudy(id, { name: newStudyName, population_id: popId });
      setNewStudyName(""); setAddStudyFor(null);
    });
  };
  const attach = (studyId, kitId) => act(() => api.attachKit(studyId, kitId));
  const detach = (studyId, kitId) => act(() => api.detachKit(studyId, kitId));
  const doDeleteStudy = (sid) => act(async () => { await api.deleteStudy(sid); setDelStudy(null); });
  const doDeletePopulation = (popId, opts) => act(async () => {
    await api.deletePopulation(id, popId, opts);
    setDelPop(null); setDelTarget("");
  });
  const share = wrap(async () => {
    await api.shareProject(id, shareEmail, shareRole);
    setShareEmail(""); setMsg("Shared.");
  });
  const removeMember = (userId) => act(() => api.unshareProject(id, userId));
  const changeRole = (email, role) => act(() => api.shareProject(id, email, role));
  const doExport = async (kind) => {
    setErr(null); setMsg(null);
    try { await downloadExport(id, kind); } catch (e) { setErr(e.message); }
  };
  const importCsv = (file) => act(async () => {
    const r = await api.importGenotypes(id, file);
    setMsg(`Imported ${r.samples} samples, ${r.consensus} genotypes (${r.markers} markers).`);
  });
  const deleteProj = async () => {
    setErr(null);
    try { await api.deleteProject(id); nav("/projects"); }
    catch (e) { setErr(e.message); }
  };

  if (err && !project) return <div className="container"><p className="error">{err}</p></div>;
  if (!project) return <div className="container"><p>Loading…</p></div>;

  // Group studies under their population; keep any population-less studies in a trailing block.
  const studiesFor = (popId) => studies.filter((s) => s.population_id === popId);
  const orphanStudies = studies.filter((s) => !populations.some((p) => p.id === s.population_id));

  const renderStudy = (s) => {
    const avail = kits.filter((k) => !s.kits?.some((x) => x.id === k.id));
    return (
      <li key={s.id} className="study-row">
        <span className="study-name">{s.name}</span>
        {!s.include_in_matching && <span className="tag">excluded from matching</span>}
        <Link to={`/studies/${s.id}/samples`}>Samples</Link>
        <span className="kit-chips">
          {(s.kits || []).map((k) => (
            <span className="chip" key={k.id}>
              {k.kit_code}
              <button className="chip-x" title="Detach kit" onClick={() => detach(s.id, k.id)}>×</button>
            </span>
          ))}
          {avail.length > 0 && (
            <select className="kit-attach" value="" onChange={(e) => {
              if (e.target.value) attach(s.id, Number(e.target.value));
            }}>
              <option value="">+ attach kit</option>
              {avail.map((k) => <option key={k.id} value={k.id}>{k.kit_code}</option>)}
            </select>
          )}
        </span>
        {delStudy === s.id ? (
          <span className="confirm-inline">
            Delete study? Its samples stay in the population.
            <button className="danger" onClick={() => doDeleteStudy(s.id)}>Delete</button>
            <button className="secondary" onClick={() => setDelStudy(null)}>Cancel</button>
          </span>
        ) : (
          <button className="danger-link" title="Delete study" onClick={() => setDelStudy(s.id)}>Delete</button>
        )}
      </li>
    );
  };

  return (
    <div className="container">
      <p><Link to="/projects">← Projects</Link></p>
      <div className="detail-head">
        <div>
          <h1>{project.name}</h1>
          <p className="muted">{project.organisation || ""}</p>
        </div>
        <div className="toolbar">
          <div className="menu-wrap">
            <button className="secondary" onClick={() => setExportOpen((o) => !o)}>Export ▾</button>
            {exportOpen && (
              <div className="menu" onMouseLeave={() => setExportOpen(false)}>
                {EXPORTS.map(([kind, label]) => (
                  <button key={kind} onClick={() => { setExportOpen(false); doExport(kind); }}>{label}</button>
                ))}
              </div>
            )}
          </div>
          <button className="secondary" title="Import genotypes CSV (wide or long-with-sequences; auto-detected)"
                  onClick={() => fileRef.current?.click()}>Import CSV</button>
          <input ref={fileRef} type="file" accept=".csv,text/csv" style={{ display: "none" }}
                 onChange={(e) => { const f = e.target.files[0]; if (f) importCsv(f); e.target.value = ""; }} />
        </div>
      </div>
      {err && <p className="error">{err}</p>}
      {msg && <p className="ok">{msg}</p>}

      <h2>Populations &amp; studies</h2>
      {populations.length === 0 ? <p className="muted">No populations yet.</p> : (
        <div className="pop-list">
          {populations.map((p) => (
            <div className="pop-block" key={p.id}>
              <div className="pop-head">
                <strong>{p.name}{" "}
                  <span className="muted small">({p.sample_count} sample{p.sample_count === 1 ? "" : "s"})</span>
                </strong>
                <span className="links">
                  <Link to={`/populations/${p.id}/samples`}>Samples</Link>
                  {" · "}
                  <Link to={`/populations/${p.id}/match`}>Animals</Link>
                  {" · "}
                  <button className="danger-link" onClick={() => { setDelPop(p.id); setDelTarget(""); }}>Delete</button>
                </span>
              </div>
              {delPop === p.id && (
                <div className="del-panel">
                  {p.sample_count === 0 ? (
                    <div className="row">
                      <span>Delete population “{p.name}”?</span>
                      <button className="danger" onClick={() => doDeletePopulation(p.id)}>Delete</button>
                      <button className="secondary" onClick={() => setDelPop(null)}>Cancel</button>
                    </div>
                  ) : (
                    <>
                      <p className="muted small">“{p.name}” has {p.sample_count} samples. Transfer them
                        (and this population’s studies) to another population, or delete them.</p>
                      <div className="row" style={{ flexWrap: "wrap" }}>
                        {populations.filter((o) => o.id !== p.id).length > 0 ? (
                          <>
                            <select value={delTarget} onChange={(e) => setDelTarget(e.target.value)}>
                              <option value="">Transfer to…</option>
                              {populations.filter((o) => o.id !== p.id).map((o) => (
                                <option key={o.id} value={o.id}>{o.name}</option>
                              ))}
                            </select>
                            <button disabled={!delTarget}
                                    onClick={() => doDeletePopulation(p.id, { reassign_to: Number(delTarget) })}>
                              Transfer &amp; delete
                            </button>
                          </>
                        ) : <span className="muted small">No other population to transfer to.</span>}
                        <button className="danger"
                                onClick={() => doDeletePopulation(p.id, { delete_samples: true })}>
                          Delete population + {p.sample_count} samples
                        </button>
                        <button className="secondary" onClick={() => setDelPop(null)}>Cancel</button>
                      </div>
                    </>
                  )}
                </div>
              )}
              <ul className="study-list">
                {studiesFor(p.id).map(renderStudy)}
                <li className="study-add">
                  {addStudyFor === p.id ? (
                    <form className="row" onSubmit={(e) => addStudy(e, p.id)}>
                      <input autoFocus placeholder="Study name" value={newStudyName}
                             onChange={(e) => setNewStudyName(e.target.value)} required />
                      <button type="submit">Add</button>
                      <button type="button" className="secondary" onClick={() => setAddStudyFor(null)}>Cancel</button>
                    </form>
                  ) : (
                    <button className="linkish" onClick={() => { setAddStudyFor(p.id); setNewStudyName(""); }}>
                      + add study
                    </button>
                  )}
                </li>
              </ul>
            </div>
          ))}
          {orphanStudies.length > 0 && (
            <div className="pop-block">
              <div className="pop-head"><strong className="muted">No population</strong></div>
              <ul className="study-list">{orphanStudies.map(renderStudy)}</ul>
            </div>
          )}
        </div>
      )}
      <form className="row" onSubmit={addPop} style={{ marginTop: ".6rem" }}>
        <input placeholder="New population name" value={popName} onChange={(e) => setPopName(e.target.value)} required />
        <button type="submit">Add population</button>
      </form>

      <h2 style={{ marginTop: "1.5rem" }}>Sharing</h2>
      {access && (
        <table className="table">
          <thead><tr><th>User</th><th>Access</th><th></th></tr></thead>
          <tbody>
            <tr>
              <td>{access.owner_email}</td>
              <td><span className="badge ok">owner</span></td>
              <td></td>
            </tr>
            {access.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td>
                  <select value={m.role} onChange={(e) => changeRole(m.email, e.target.value)}>
                    <option value="viewer">viewer</option>
                    <option value="editor">editor</option>
                  </select>
                </td>
                <td><button className="secondary" onClick={() => removeMember(m.user_id)}>Remove</button></td>
              </tr>
            ))}
            {access.members.length === 0 && (
              <tr><td colSpan="3" className="muted">Not shared with anyone yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
      <form className="row" onSubmit={share} style={{ marginTop: ".6rem" }}>
        <input type="email" placeholder="user email" value={shareEmail} onChange={(e) => setShareEmail(e.target.value)} required />
        <select value={shareRole} onChange={(e) => setShareRole(e.target.value)}>
          <option value="viewer">viewer</option>
          <option value="editor">editor</option>
        </select>
        <button type="submit">Share</button>
      </form>

      {user && (project.owner_user_id === user.id || user.role === "admin") && (
        <div className="danger-zone">
          <h2>Danger zone</h2>
          {!confirming ? (
            <button className="danger" onClick={() => { setConfirming(true); setConfirmName(""); }}>
              Delete project…
            </button>
          ) : (
            <div className="danger-box">
              <p><strong>⚠ This permanently deletes “{project.name}”</strong> and all of its
                populations, samples, genotypes, animals and matching results. This cannot be undone.
                (Jobs are kept but detached from the project.)</p>
              <p className="muted small">Type the project name to confirm:</p>
              <div className="row">
                <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)}
                       placeholder={project.name} />
                <button className="secondary" onClick={() => setConfirming(false)}>Cancel</button>
                <button className="danger" disabled={confirmName !== project.name} onClick={deleteProj}>
                  Delete permanently
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
